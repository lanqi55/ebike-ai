
from operator import itemgetter
from langchain_chroma import Chroma
from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from read_hardware import get_latest_battery_data
from embedding_utils import MyDashScopeEmbedding
from config import config
from utils.logger import get_logger

logger = get_logger(__name__)


DB_PATH = config.path.chroma_db


# 1、初始化向量模型（必须和建库完全匹配）
embeddings = MyDashScopeEmbedding(
    model=config.embedding.model,
    api_key=config.embedding.api_key,
)
vectorstore = Chroma(persist_directory=DB_PATH, embedding_function=embeddings)

# 检索器，每次取相似度最高的2条文档（减少噪音）
retriever = vectorstore.as_retriever(search_kwargs={"k": config.embedding.search_top_k})

# 2、初始化通义千问对话大模型
llm = ChatTongyi(
    model=config.llm.model,
    dashscope_api_key=config.llm.api_key,
    temperature=config.llm.temperature,
    model_kwargs={"max_tokens": config.llm.max_tokens},
)

# 3、维修定制提示词
template = """你是电动车维修专家。根据硬件电压数据和维修知识库，给出诊断结论。

【硬件电压数据】：{hardware_data}
【用户描述故障】：{question}
【维修知识库】：{context}

请严格按以下格式输出，每项一行，禁止展开长篇论述：

🔧 故障定位：（用1句话指出损坏的元器件）
📊 判断依据：（用1句话说清电压数据如何支撑判断）
🛠️ 检修步骤：
  1. （步骤1，≤20字）
  2. （步骤2，≤20字）
  3. （步骤3，≤20字）
📦 需更换配件：（列出配件名，无可写"无"）

总字数控制在200字以内，禁止重复啰嗦。"""
prompt = PromptTemplate.from_template(template)

# 工具函数：拼接多条检索出来的文档
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

# 4、LCEL组装完整RAG链路（流水线模式——已废弃，保留供 test_agent_eval 使用）
rag_chain = (
    {
        "context": itemgetter("question") | retriever | format_docs,
        "question": itemgetter("question"),
        "hardware_data": itemgetter("hardware_data")
    }
    | prompt
    | llm
    | StrOutputParser()
)

if __name__ == "__main__":
    battery_info = get_latest_battery_data()
    if not battery_info:
        logger.error("错误：未检测到电池电压数据，请先运行 sim_hardware.py 生成模拟数据")
        exit()

    fault_input = input("请输入电动车故障描述：")
    try:
        answer = rag_chain.invoke({
            "question": fault_input,
            "hardware_data": str(battery_info)
        })
    except Exception as e:
        logger.error(f"\n❌ 诊断出错: {e}")
        exit()

    print("\n========== AI维修诊断结果（流水线模式）==========")
    print(answer)
