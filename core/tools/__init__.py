"""域工具模块的落地位。

S2 期间域模块逐波新增；本 `__init__` 刻意不写任何 re-export，
否则在域模块全部落地前，任何 `import core.tools` 都会连带炸 import。
调用方按需 `from core.tools import vocabulary` 这样显式取子模块。
"""
