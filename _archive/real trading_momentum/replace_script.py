import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacements = {
    '1분봉': '3분봉',
    '1min': '3min',
    'candles_1m': 'candles_3m',
    'latest_1m': 'latest_3m',
    'prev_1m': 'prev_3m',
    'tema20_1m': 'tema20_3m',
    'sma20_1m': 'sma20_3m',
    'sma40_1m': 'sma40_3m',
    'is_1m_dead_cross': 'is_3m_dead_cross',
    'is_1m_gold_cross': 'is_3m_gold_cross',
    'sugeub_1m_ok': 'sugeub_3m_ok',
    '"1m"': '"3m"',
    "'1m'": "'3m'",
    '1m 모드': '3m 모드',
    '1m TEMA3': '3m TEMA3',
    '1m 데드크로스': '3m 데드크로스',
    '1m 골든크로스': '3m 골든크로스',
    '1m 재매수': '3m 재매수',
    '1m 추적': '3m 추적',
}

for k, v in replacements.items():
    content = content.replace(k, v)

with open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Replaced successfully")
