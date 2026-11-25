"""借件归还前双语状况记录核对工具。

子模块划分：
- model：资料记录、观察、特征、放行结论等数据结构
- lexicon：双语部位、材质层、状态家族与肯定程度词表
- parser：从双语文字报告抽取带原文证据的观察
- geometry：照片参照轴与物件方位的换算
- reconcile：旧痕/新增/排除/分歧的核对与合并
- cases：封箱组合、签字绑定与放行
- loader / cli：批次资料装载与命令行入口
"""

__all__ = ["model", "lexicon", "parser", "geometry", "reconcile", "cases", "loader", "cli"]
