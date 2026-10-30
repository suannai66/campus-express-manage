"""应用/编排层：用例级流程编排，串联 core / channels / query，幂等键贯穿（Q-04）。

编排只做流程串联，不做资金状态变更——资金变更一律经 core/wallet_core.py（唯一资金入口）。
"""
