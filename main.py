"""主交互入口 — stocks_analysis

用法:
    python main.py                          # 执行今日选股扫描
    python main.py scan                     # 同上
    python main.py scan --date 2026-02-13   # 指定日期选股
    python main.py kline 000001             # 单股K线分析
    python main.py sector                   # 板块强弱排名
    python main.py backtest                 # 策略回测（默认 base 策略）

详细帮助:
    python main.py scan --help
    python main.py kline --help
    python main.py sector --help
    python main.py backtest --help
"""
import os
import sys

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from config import last_trading_day


COMMANDS = {
    'scan':     ('每日选股扫描',    'analyze.daily_scan',  'main'),
    'kline':    ('K线统计分析',     'analyze.kline_stats', 'main'),
    'sector':   ('板块/概念分析',   'analyze.sector',      'main'),
    'backtest': ('策略回测',        'analyze.strategy',    'main'),
}


def print_help():
    print(__doc__)
    print("可用命令:")
    for cmd, (desc, _, _) in COMMANDS.items():
        print(f"  {cmd:<12}  {desc}")
    print()


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
        print_help()
        return

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        # 默认执行 scan
        sys.argv.insert(1, 'scan')
        cmd = 'scan'

    _, module_path, func_name = COMMANDS[cmd]

    # 移除第一个位置参数（子命令名），让子模块的 parser 正常工作
    sys.argv = [sys.argv[0]] + sys.argv[2:]

    import importlib
    module = importlib.import_module(module_path)
    getattr(module, func_name)()


if __name__ == '__main__':
    main()
