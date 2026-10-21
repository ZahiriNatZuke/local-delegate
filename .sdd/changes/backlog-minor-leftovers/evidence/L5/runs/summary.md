## Por configuración

| Config | Válidas | Truncadas | `finish_reason` ≠ stop | Fallos de control | Razonamiento (chars, mediana) | Latencia (s, mediana) | Latencia (s, máx) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ref | 15/15 | 0 | 0 | 0 | 0 | 8.0 | 27.9 |
| b256 | 8/15 | 6 | 6 | 6 | 989 | 14.9 | 39.1 |
| b512 | 8/15 | 6 | 6 | 6 | 1903 | 18.9 | 43.2 |
| b1024 | 5/15 | 10 | 10 | 8 | 3827 | 37.1 | 54.1 |
| b2048 | 14/15 | 1 | 1 | 1 | 7164 | 47.8 | 74.5 |
| b4096 | 15/15 | 0 | 0 | 0 | 8814 | 53.0 | 90.7 |

## Por celda (configuración × entrada, 3 repeticiones)

| Config | Entrada | Válidas | Truncadas | Controles | Razonamiento (chars) | `tokens_out` | Latencia (s) | Hashes distintos |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ref | explain-json_state | 3/3 | 0 | ok, ok, ok | 0, 0, 0 | 373, 327, 306 | 27.9, 8.3, 7.6 | 3 |
| ref | explain-chains | 3/3 | 0 | ok, ok, ok | 0, 0, 0 | 261, 325, 370 | 11.2, 10.7, 11.2 | 3 |
| ref | commit-b0ba620 | 3/3 | 0 | ok, ok, ok | 0, 0, 0 | 108, 99, 98 | 5.6, 4.8, 4.8 | 3 |
| ref | commit-a9f84e7 | 3/3 | 0 | ok, ok, ok | 0, 0, 0 | 100, 119, 123 | 3.9, 4.0, 4.1 | 3 |
| ref | boilerplate-duration | 3/3 | 0 | ok, ok, ok | 0, 0, 0 | 335, 408, 465 | 8.0, 9.3, 10.7 | 3 |
| b256 | explain-json_state | 2/3 | 1 | ok, ok, ok | 1074, 1055, 1101 | 529, 956, 508 | 12.5, 20.9, 11.6 | 3 |
| b256 | explain-chains | 2/3 | 0 | ok, ok, leak | 1122, 1085, 1089 | 548, 543, 550 | 16.3, 14.9, 14.9 | 3 |
| b256 | commit-b0ba620 | 3/3 | 0 | ok, ok, ok | 1004, 921, 968 | 365, 387, 270 | 10.3, 10.6, 8.2 | 3 |
| b256 | commit-a9f84e7 | 1/3 | 2 | ok, not_conventional, not_conventional | 982, 983, 989 | 363, 956, 956 | 9.0, 21.3, 21.3 | 3 |
| b256 | boilerplate-duration | 0/3 | 3 | syntax_error, syntax_error, syntax_error | 945, 808, 787 | 1792, 1792, 1792 | 39.1, 38.3, 37.5 | 3 |
| b512 | explain-json_state | 2/3 | 1 | ok, ok, ok | 2338, 2285, 2281 | 746, 767, 1212 | 16.5, 17.0, 26.5 | 3 |
| b512 | explain-chains | 3/3 | 0 | ok, ok, ok | 2314, 2219, 2277 | 701, 740, 740 | 17.9, 18.9, 20.2 | 3 |
| b512 | commit-b0ba620 | 1/3 | 2 | not_conventional, ok, not_conventional | 1865, 1860, 1850 | 1212, 709, 1212 | 27.5, 17.3, 28.1 | 3 |
| b512 | commit-a9f84e7 | 0/3 | 2 | not_conventional, leak, leak | 1900, 1933, 1903 | 1212, 1212, 672 | 26.5, 27.0, 15.6 | 3 |
| b512 | boilerplate-duration | 2/3 | 1 | ok, ok, syntax_error | 1539, 1654, 1542 | 744, 747, 2048 | 16.2, 16.4, 43.2 | 3 |
| b1024 | explain-json_state | 2/3 | 1 | ok, ok, ok | 4475, 4647, 4625 | 1269, 1724, 1246 | 27.5, 36.9, 27.1 | 3 |
| b1024 | explain-chains | 2/3 | 1 | leak, ok, ok | 4348, 4444, 4452 | 1724, 1265, 1268 | 39.1, 29.7, 29.9 | 3 |
| b1024 | commit-b0ba620 | 1/3 | 2 | leak, ok, not_conventional | 3319, 3809, 3827 | 1724, 1147, 1724 | 38.5, 26.3, 38.2 | 3 |
| b1024 | commit-a9f84e7 | 0/3 | 3 | not_conventional, not_conventional, ok | 3847, 3286, 3821 | 1724, 1724, 1724 | 38.1, 37.1, 37.1 | 3 |
| b1024 | boilerplate-duration | 0/3 | 3 | syntax_error, syntax_error, syntax_error | 3312, 3057, 2796 | 2560, 2560, 2560 | 54.1, 53.8, 53.6 | 3 |
| b2048 | explain-json_state | 3/3 | 0 | ok, ok, ok | 9048, 4389, 8319 | 2246, 1233, 2099 | 47.8, 26.4, 44.5 | 3 |
| b2048 | explain-chains | 3/3 | 0 | ok, ok, ok | 7164, 8535, 5560 | 1860, 2325, 1615 | 42.5, 51.5, 36.9 | 3 |
| b2048 | commit-b0ba620 | 3/3 | 0 | ok, ok, ok | 7129, 7305, 7552 | 2190, 2149, 2231 | 48.5, 48.0, 49.3 | 3 |
| b2048 | commit-a9f84e7 | 3/3 | 0 | ok, ok, ok | 7473, 6713, 7434 | 2205, 2274, 2240 | 47.7, 47.9, 47.5 | 3 |
| b2048 | boilerplate-duration | 2/3 | 1 | ok, ok, syntax_error | 6514, 5881, 5478 | 2334, 2289, 3584 | 49.3, 47.8, 74.5 | 3 |
| b4096 | explain-json_state | 3/3 | 0 | ok, ok, ok | 8814, 11681, 4261 | 2187, 3351, 1215 | 47.8, 70.6, 26.4 | 3 |
| b4096 | explain-chains | 3/3 | 0 | ok, ok, ok | 8694, 3942, 7094 | 2277, 1149, 1868 | 50.8, 27.3, 42.4 | 3 |
| b4096 | commit-b0ba620 | 3/3 | 0 | ok, ok, ok | 9462, 9435, 7722 | 2730, 2613, 2394 | 59.0, 56.5, 52.5 | 3 |
| b4096 | commit-a9f84e7 | 3/3 | 0 | ok, ok, ok | 14030, 7629, 8693 | 4020, 2214, 2474 | 84.5, 47.2, 53.0 | 3 |
| b4096 | boilerplate-duration | 3/3 | 0 | ok, ok, ok | 13146, 11671, 12875 | 4352, 4344, 4312 | 90.6, 90.4, 90.7 | 3 |

Modelos: ['qwen36-35b-a3b']; reasoning_skipped: 0; chunks: {None}
