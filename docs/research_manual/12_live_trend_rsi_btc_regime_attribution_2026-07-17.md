# 38-coin Trend BTC-regime attribution

Research-only. This artifact does not authorize observer, paper execution, or live trading.

- Dataset fingerprint: `bd4188fb62cb1aada385ed2bead08f83dbed59e57342fc1653db0cb0b31d3955`
- Baseline manifest: `a98dfe8e60d446b2b3a0370ea52fc2d25c3ef8e288fcd2c562f9b674076cb316`
- Candidate manifest: `d3afebffa0fd0e069d91be8d73fbda7542262f939c02e219bfa19ab7f5ddcb99`
- Execution fixture fingerprint: `61d8136b56eda10118c6f3c78b018c4e002c393bed84204651fb222f7eda33bf`
- BTC regime: completed 7-day close change; bull > 3%, bear < -3%; bucket sample floor = 10 trades.

## 120 days

Verdict: `insufficient_sample`. A small bucket is evidence-insufficient, not a promotion or rejection result.

### Executed portfolio

| BTC regime / direction | Baseline trades | Candidate trades | Candidate net PnL | Delta net PnL | Candidate top-1 coin |
|---|---:|---:|---:|---:|---|
| bear:long | 1 | 0 | 0.0 | 42.817 | - |
| bear:short | 7 | 3 | -10.0898 | 3.2457 | IOTA (-81.701) |
| bull:long | 4 | 0 | 0.0 | -18.1743 | - |
| bull:short | 0 | 0 | 0.0 | 0.0 | - |
| neutral:long | 8 | 0 | 0.0 | 358.9049 | - |
| neutral:short | 0 | 1 | 231.5008 | 231.5008 | SKY (231.5008) |

### Raw entry opportunities before two-position capacity

| BTC regime / direction | Raw | Baseline allowed | Candidate allowed | Retained | Removed |
|---|---:|---:|---:|---:|---:|
| bear:long | 43 | 13 | 2 | 2 | 11 |
| bear:short | 213 | 29 | 27 | 27 | 2 |
| bull:long | 59 | 40 | 9 | 9 | 31 |
| bull:short | 9 | 0 | 0 | 0 | 0 |
| neutral:long | 59 | 27 | 10 | 10 | 17 |
| neutral:short | 36 | 5 | 5 | 5 | 0 |

Candidate total concentration: top-1={'coin': 'SKY', 'net_pnl': 231.5008}; top-3 absolute share=1.0; largest trade absolute share=0.428526.

## 180 days

Verdict: `insufficient_sample`. A small bucket is evidence-insufficient, not a promotion or rejection result.

### Executed portfolio

| BTC regime / direction | Baseline trades | Candidate trades | Candidate net PnL | Delta net PnL | Candidate top-1 coin |
|---|---:|---:|---:|---:|---|
| bear:long | 3 | 0 | 0.0 | -20.9638 | - |
| bear:short | 4 | 6 | -160.2367 | -92.8253 | HYPE (-70.7844) |
| bull:long | 12 | 7 | 104.5921 | 227.7926 | LTC (72.3876) |
| bull:short | 1 | 3 | -186.1332 | -131.0951 | PAXG (-66.9584) |
| neutral:long | 6 | 3 | -93.7349 | 28.5683 | NEO (-76.3308) |
| neutral:short | 8 | 7 | -92.2211 | 51.4728 | DOGE (216.5321) |

### Raw entry opportunities before two-position capacity

| BTC regime / direction | Raw | Baseline allowed | Candidate allowed | Retained | Removed |
|---|---:|---:|---:|---:|---:|
| bear:long | 49 | 16 | 3 | 3 | 13 |
| bear:short | 229 | 37 | 35 | 35 | 2 |
| bull:long | 115 | 57 | 8 | 8 | 49 |
| bull:short | 31 | 11 | 6 | 6 | 5 |
| neutral:long | 111 | 49 | 12 | 12 | 37 |
| neutral:short | 89 | 40 | 29 | 29 | 11 |

Candidate total concentration: top-1={'coin': 'DOGE', 'net_pnl': 216.5321}; top-3 absolute share=0.439554; largest trade absolute share=0.190451.

## 240 days

Verdict: `insufficient_sample`. A small bucket is evidence-insufficient, not a promotion or rejection result.

### Executed portfolio

| BTC regime / direction | Baseline trades | Candidate trades | Candidate net PnL | Delta net PnL | Candidate top-1 coin |
|---|---:|---:|---:|---:|---|
| bear:long | 3 | 0 | 0.0 | -48.8843 | - |
| bear:short | 9 | 5 | -269.4582 | -1017.7944 | CC (-108.6302) |
| bull:long | 8 | 3 | -6.4318 | 126.3877 | SOL (-99.2746) |
| bull:short | 0 | 0 | 0.0 | 0.0 | - |
| neutral:long | 13 | 3 | -134.2068 | 454.122 | HYPE (-81.7799) |
| neutral:short | 3 | 5 | 1133.943 | 1335.7765 | DOGE (652.2629) |

### Raw entry opportunities before two-position capacity

| BTC regime / direction | Raw | Baseline allowed | Candidate allowed | Retained | Removed |
|---|---:|---:|---:|---:|---:|
| bear:long | 112 | 25 | 5 | 5 | 20 |
| bear:short | 457 | 64 | 60 | 60 | 4 |
| bull:long | 152 | 83 | 13 | 13 | 70 |
| bull:short | 64 | 12 | 6 | 6 | 6 |
| neutral:long | 174 | 79 | 17 | 17 | 62 |
| neutral:short | 185 | 52 | 41 | 41 | 11 |

Candidate total concentration: top-1={'coin': 'DOGE', 'net_pnl': 652.2629}; top-3 absolute share=0.627042; largest trade absolute share=0.307954.

