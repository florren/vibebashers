"""Живая аудиосессия (T-183): кадры PCM16 / реплики из браузера → STT → реплики → детектор мисселлинга → алерты → отчёт при закрытии."""

from __future__ import annotations

import asyncio
import datetime as dt
import time
import wave
from typing import Any

import psycopg

from app.compliance import taxonomy
from app.compliance.session import ComplianceService, Session
from app.compliance.transcripts import _finding, _finish_report
from app.config import get_settings
from app.db.session import psycopg_dsn
from app.logging import get_logger
from app.stt import registry, speakers
from app.stt.base import STTResult, pcm_split_stereo

log = get_logger(__name__)

SILENCE_CLOSE_S = 90.0


class LiveSession:
    def __init__(
        self, app: Any, session_id: int, *, provider_code: str | None, sample_rate: int = 16000, channels: int = 1
    ) -> None:
        self.app, self.session_id = app, session_id
        self.provider = registry.get(provider_code)
        self.sample_rate, self.channels = sample_rate, channels
        self.conn: psycopg.AsyncConnection[Any] | None = None
        self.svc: ComplianceService | None = None
        self.s: Session | None = None
        self.streams: dict[int, Any] = {}
        self.seq = 0
        self.speaker = "employee"  # активная роль в режиме manual
        self.prev_speaker: str | None = None
        self.findings: list[dict[str, Any]] = []
        self.turns: list[dict[str, Any]] = []
        self.employee_texts: list[tuple[int, str]] = []
        self.pmap: dict[str, Any] = {}
        self.t_start = time.perf_counter()
        self.audio_bytes = 0
        self.closed = False
        self._lock = asyncio.Lock()
        self._last_partial: dict[int, str] = {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> Session:
        s = get_settings()
        self.conn = await psycopg.AsyncConnection.connect(psycopg_dsn(), autocommit=True)
        row = await (await self.conn.execute("select sim_time, current_run_id from sim_state where id = 1")).fetchone()
        sim = getattr(self.app.state, "sim", None)
        sim_time = sim.clock.sim_time if sim else (row[0] if row else dt.datetime.now(dt.UTC))
        sess_row = await (
            await self.conn.execute(
                "select run_id, alert_threshold, diarization_mode, status from audio_sessions where id = %s",
                (self.session_id,),
            )
        ).fetchone()
        if not sess_row:
            raise LookupError("session")
        if sess_row[3] == "closed":
            raise RuntimeError("session closed")
        self.svc = ComplianceService(
            self.conn,
            run_id=int(sess_row[0]),
            sim_time=sim_time,
            chain=self.app.state.llm_chain,
            profile=self.app.state.llm_chain.profile_for("fast", self.app.state.llm_profile),
            alert_threshold=int(sess_row[1] or s.compliance_alert_threshold),
        )
        sess = await self.svc.get_session(self.session_id)
        if sess is None:
            raise LookupError("session")
        self.s = sess
        self.mode = str(sess_row[2])
        self.pmap = {p.code: p for p in await taxonomy.load_patterns(self.conn, only_active=True)}
        if self.provider.code != "browser":
            n = 2 if (self.mode == "stereo" and self.channels == 2) else 1
            for ch in range(1, n + 1):
                self.streams[ch] = await asyncio.to_thread(self.provider.open_stream, self.sample_rate)
        return sess

    async def finish(self) -> dict[str, Any] | None:
        if self.closed or self.svc is None or self.s is None or self.conn is None:
            return None
        self.closed = True
        out: list[dict[str, Any]] = []
        for ch, st in self.streams.items():
            tail = await asyncio.to_thread(st.finish)
            if tail:
                out.append(await self._final(tail, ch))
        header = f"Живая встреча {self.s.public_id} ({self.s.employee_name}, ВСП {self.s.branch_code})"
        report = await _finish_report(
            self.conn,
            self.svc,
            self.findings,
            self.employee_texts,
            self.turns,
            "branch_retail",
            header=header,
            session_id=self.s.id,
        )
        report = {
            **report,
            "audio_session_id": self.s.id,
            "branch_code": self.s.branch_code,
            "source": self.s.source,
            "stt_provider": self.provider.code,
        }
        await self.svc.close_session(self.s, report)
        if self.findings:
            await self.conn.execute(
                "update employees set violations_count = violations_count + %s where id = %s",
                (len(self.findings), self.s.employee_id),
            )
        await self.svc._emit(self.s, "compliance.report_ready")
        await self.conn.execute(
            "insert into stt_metrics (session_id, provider, model, audio_seconds, cpu_ms) values (%s, %s, %s, %s, %s)",
            (
                self.s.id,
                self.provider.code,
                getattr(self.provider, "model_dir", None) and self.provider.model_dir.name,
                round(self.audio_bytes / (2 * self.sample_rate * max(1, self.channels)), 2),
                int((time.perf_counter() - self.t_start) * 1000),
            ),
        )
        await self.conn.close()
        log.info(
            "stt_session_closed",
            session_id=self.s.id,
            utterances=self.seq,
            findings=len(self.findings),
            provider=self.provider.code,
        )
        return {"report": report, "finals": out}

    # ------------------------------------------------------------------ input
    def set_speaker(self, speaker: str) -> None:
        if speaker in ("employee", "client"):
            self.speaker = speaker

    async def feed_audio(self, pcm: bytes) -> list[dict[str, Any]]:
        if self.closed or not self.streams:
            return []
        self.audio_bytes += len(pcm)
        chunks: dict[int, bytes] = {}
        if len(self.streams) == 2:
            left, right = pcm_split_stereo(pcm)
            chunks = {1: left, 2: right}
        elif self.channels == 2:
            left, _ = pcm_split_stereo(pcm)
            chunks = {1: left}
        else:
            chunks = {1: pcm}
        out: list[dict[str, Any]] = []
        for ch, data in chunks.items():
            results: list[STTResult] = await asyncio.to_thread(self.streams[ch].feed, data)
            for r in results:
                if r.type == "partial":
                    if self._last_partial.get(ch) != r.text:
                        self._last_partial[ch] = r.text
                        out.append(self._msg("partial", r.text, ch, latency_ms=r.latency_ms))
                else:
                    self._last_partial.pop(ch, None)
                    out.append(await self._final(r, ch))
        return out

    async def feed_text(self, text: str, *, is_final: bool, speaker: str | None = None) -> list[dict[str, Any]]:
        """Реплики от провайдера browser (Web Speech API)."""
        if self.closed:
            return []
        text = text.strip()
        if not text:
            return []
        if speaker:
            self.set_speaker(speaker)
        if not is_final:
            return [self._msg("partial", text, 1)]
        return [await self._final(STTResult("final", text), 1)]

    # ------------------------------------------------------------------ internals
    def _msg(self, typ: str, text: str, channel: int, **extra: Any) -> dict[str, Any]:
        base: dict[str, Any] = {
            "type": typ,
            "session_id": self.session_id,
            "channel": channel,
            "text": text,
            "seq": None,
            "words": [],
            "confidence": None,
            "latency_ms": None,
            "provider": self.provider.code,
            "error": None,
        }
        base.update(extra)
        return base

    async def _final(self, r: STTResult, channel: int) -> dict[str, Any]:
        assert self.svc is not None and self.s is not None and self.conn is not None
        async with self._lock:
            self.seq += 1
            seq = self.seq
            if self.mode == "stereo" and len(self.streams) == 2:
                speaker, conf, src = ("employee" if channel == 1 else "client"), 1.0, "channel"
            elif self.mode == "auto":
                a = speakers.attribute(r.text, self.prev_speaker, self.turns[-6:])
                speaker, conf, src = str(a["speaker"]), float(a["confidence"]), "llm"
            else:
                speaker, conf, src = self.speaker, 1.0, "manual"
            self.prev_speaker = speaker
            elapsed_ms = int((time.perf_counter() - self.t_start) * 1000)
            t0 = int(r.words[0]["t0"] * 1000) if r.words else max(0, elapsed_ms - max(1000, len(r.text) * 60))
            t1 = int(r.words[-1]["t1"] * 1000) if r.words else elapsed_ms
            uid = await self.svc.add_utterance(
                self.s,
                seq=seq,
                speaker=speaker,
                text=r.text,
                t0_ms=t0,
                t1_ms=t1,
                speaker_source=src,
                speaker_confidence=conf,
                stt_confidence=r.confidence,
                latency_ms=r.latency_ms,
            )
            if r.words:
                from app.sim.events import dumps

                await self.conn.execute("update utterances set words = %s::jsonb where id = %s", (dumps(r.words), uid))
            self.turns.append({"seq": seq, "speaker": speaker, "text": r.text, "t0_ms": t0, "t1_ms": t1})
            trigger: dict[str, Any] | None = None
            if speaker == "employee":
                self.employee_texts.append((seq, r.text))
                for trig in await self.svc.process_utterance(self.s, uid, r.text, transcript_kind="branch_retail"):
                    if trig["status"] == "confirmed":
                        self.findings.append(_finding(seq, trig, self.pmap.get(trig["pattern_code"])))
                        trigger = trig
            if r.latency_ms is not None:
                await self.conn.execute(
                    "insert into stt_metrics (session_id, provider, model, final_latency_ms, audio_seconds) values (%s, %s, %s, %s, %s)",
                    (
                        self.s.id,
                        self.provider.code,
                        getattr(getattr(self.provider, "model_dir", None), "name", None),
                        r.latency_ms,
                        round((t1 - t0) / 1000, 2),
                    ),
                )
            msg = self._msg(
                "final", r.text, channel, seq=seq, words=r.words, confidence=r.confidence, latency_ms=r.latency_ms
            )
            msg["utterance"] = {
                "utterance_id": uid,
                "seq": seq,
                "speaker": speaker,
                "speaker_confidence": conf,
                "speaker_source": src,
                "text": r.text,
                "t0_ms": t0,
                "t1_ms": t1,
            }
            if trigger:
                msg["trigger"] = {
                    k: trigger.get(k)
                    for k in (
                        "id",
                        "pattern_code",
                        "confidence",
                        "quote",
                        "explanation_ru",
                        "recommendation_ru",
                        "status",
                    )
                }
            row = await (
                await self.conn.execute(
                    "select trigger_count, status, alert_threshold from audio_sessions where id = %s", (self.s.id,)
                )
            ).fetchone()
            if row:
                msg["session"] = {"trigger_count": int(row[0]), "status": str(row[1]), "alert_threshold": int(row[2])}
            return msg


# 100 мс PCM16 LE 16 кГц: моно 3200 байт, стерео — interleaved на оба канала.
_FILE_SAMPLE_RATE = 16000
_FILE_CHUNK_FRAMES = 1600
_FILE_SAMPLE_WIDTH = 2


class _FilePlayback:
    def __init__(self, live: LiveSession) -> None:
        self.live = live
        self.stop = asyncio.Event()


_file_playbacks: dict[int, _FilePlayback] = {}


def set_file_speaker(session_id: int, speaker: str) -> None:
    playback = _file_playbacks.get(session_id)
    if playback is not None:
        playback.live.set_speaker(speaker)


def request_stop(session_id: int) -> None:
    playback = _file_playbacks.get(session_id)
    if playback is not None:
        playback.stop.set()


async def play_wav(app: Any, session_id: int, path: str, *, provider_code: str | None, channels: int) -> None:
    """Читает WAV чанками в реальном темпе и кормит ту же LiveSession. Частичные наружу не шлёт, байты не сохраняет."""
    live = LiveSession(app, session_id, provider_code=provider_code, sample_rate=_FILE_SAMPLE_RATE, channels=channels)
    playback = _FilePlayback(live)
    _file_playbacks[session_id] = playback
    try:
        await live.start()
        with wave.open(path, "rb") as wf:
            while not playback.stop.is_set():
                pcm = wf.readframes(_FILE_CHUNK_FRAMES)
                if not pcm:
                    break
                await live.feed_audio(pcm)
                if playback.stop.is_set():
                    break
                duration = len(pcm) / (_FILE_SAMPLE_RATE * channels * _FILE_SAMPLE_WIDTH)
                await asyncio.sleep(duration)
    except Exception:  # noqa: BLE001 — сбой файла не должен оставлять задачу без журнала
        log.exception("file_playback_failed", session_id=session_id)
    finally:
        _file_playbacks.pop(session_id, None)
        try:
            await live.finish()
        except Exception:  # noqa: BLE001
            log.exception("file_playback_finish_failed", session_id=session_id)
