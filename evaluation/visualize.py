
import pandas as pd
import matplotlib.pyplot as plt

# 0. 中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 1. 读报告
df = pd.read_excel("evaluation/report.xlsx")

# 2.算每个维度的通过率
cols = ["关键词命中率", "格式合规率", "幻觉检测", "工具调用正确率"]
pass_rates = df[cols].mean()

# 3. 画柱状图
pass_rates.plot(kind="bar")
plt.title("各维度通过率")
plt.ylabel("通过率")
plt.ylim(0, 1)                       # y 轴范围 0~1
plt.xticks(rotation=0)
plt.savefig("evaluation/report.png")  # 存成图片
plt.show()                            # 弹出窗口看