Публичная цепочка НУЦ Минцифры для GigaChat. Получена 28.10.2026 с проверкой HTTPS:

- https://gu-st.ru/content/lending/russian_trusted_root_ca_pem.crt
- https://gu-st.ru/content/lending/russian_trusted_sub_ca_pem.crt

Root: действителен до 27.02.2032; SHA-256 fingerprint
`D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`.
Sub: действителен до 06.03.2027; SHA-256 fingerprint
`BB:BD:E2:10:3E:79:0B:99:9E:C6:2B:D0:3C:F6:25:A5:A2:E7:C3:16:E1:0A:FE:6A:49:0E:ED:EA:D8:B3:FD:9B`.

`gigachat-ca.pem` — конкатенация этих двух PEM с переводом строки между сертификатами.
При обновлении загрузите файлы по HTTPS без отключения проверки сертификатов, проверьте
`openssl x509 -in <file> -noout -subject -issuer -dates -fingerprint -sha256` и
`openssl verify -CAfile russian_trusted_root_ca_pem.crt russian_trusted_sub_ca_pem.crt`,
после чего пересоберите bundle и обновите fingerprints здесь. Закрытых ключей нет.

Клиент добавляет bundle к стандартному certifi SSLContext. Системные CA и файл certifi не меняются.
Для собственного bundle используйте GIGACHAT_CA_BUNDLE_FILE; путь должен существовать внутри процесса/контейнера backend.
