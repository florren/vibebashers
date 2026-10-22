# Карта субъектов РФ

`russia-regions.topo.json` — TopoJSON (83 полигона) на основе открытого набора
[codeforamerica/click_that_hood — russia.geojson](https://github.com/codeforamerica/click_that_hood/blob/master/public/data/russia.geojson)
(код MIT, геоданные OpenStreetMap © участники OSM, ODbL), упрощённый mapshaper (`-simplify 10% keep-shapes`, quantization 10000), ~68 КБ.
Свойства геометрий: `code` — код субъекта из `regions.code`, `name` — название в источнике.

Субъекты без полигона в источнике (коды 90–95) рисуются маркером по центроиду из `regions` (`/api/map/heat` отдаёт `lat`/`lon`).
