
from langchain_community.document_loaders import DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_community.vectorstores import Chroma
from embedding_utils import MyDashScopeEmbedding
from config import config
from utils.logger import get_logger

logger = get_logger(__name__)

# 1、定义文档路径、向量库存放路径
DOC_PATH = config.path.repair_docs
DB_PATH = config.path.chroma_db

def build_repair_knowledge_base():
    # 分别加载docx、pdf，规避unstructured依赖
    loader_docx = DirectoryLoader(DOC_PATH, glob="**/*.docx", loader_cls=Docx2txtLoader)
    loader_pdf = DirectoryLoader(DOC_PATH, glob="**/*.pdf", loader_cls=PyPDFLoader)
    raw_docs = loader_docx.load() + loader_pdf.load()

    logger.info(f"一共加载文档数量：{len(raw_docs)}")
    if len(raw_docs) == 0:
        logger.warning("提示：repair_docs 里面没有可读取的docx/pdf文档")
        return

    # 文本切片：过长文档拆分小块，检索更精准
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=300,  # 每一段最大字数
        chunk_overlap=50  # 两段重叠50个字，避免上下文割裂
    )
    split_doc = splitter.split_documents(raw_docs)
    logger.info(f"拆分后文本片段总数：{len(split_doc)}")

    # 初始化Embedding嵌入模型
    embedding = MyDashScopeEmbedding(model=config.embedding.model,api_key=config.embedding.api_key)

    # 存入本地向量数据库
    vector_da = Chroma.from_documents(
        documents=split_doc,
        embedding=embedding,
        persist_directory=DB_PATH
    )
    vector_da.persist()
    logger.info("维修知识库构建完成，向量库已持久化本地！")


if __name__ == "__main__":
    build_repair_knowledge_base()
