"""
（三）用 LangChain 重写 RAG —— 演示入口

用 LangChain 组件重走 02 模块的整条 RAG 链路，逐环对照：

    02模块手写                       LangChain 组件
    ──────────────                  ─────────────────────────
    Article 数据类                   Document（page_content + metadata）
    chunker.py 手写切片              MarkdownHeaderTextSplitter / Recursive...
    embedder.py                     Embeddings 接口（我们自己实现的 FastEmbed 包装）
    Qdrant 手动 upsert/query        QdrantVectorStore + as_retriever()
    手动组装 Prompt + 调LLM          prompt | model 管道

运行方式：
    cd 到本 project 目录 -> uv sync -> uv run python main.py
    （演示 1~3 离线可跑，演示 4 需要 LLM Key）
"""

from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_qdrant import QdrantVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter
from rich.console import Console
from rich.panel import Panel

from fastembed_embeddings import FastEmbedEmbeddings
from loader import load_articles  # 02 模块写的解析器，直接复用！

console = Console()
DATA_DIR = "data"


def step_1_load_documents() -> list[Document]:
    """第 1 步：加载文章并转成 LangChain 的 Document。

    Document 就是 LangChain 版的「带元数据的文本」：
        page_content -> 我们 Article 的 content
        metadata     -> article_id / title / tags 等
    我们的 loader.py 不用改一行，做个格式转换即可 —— 自己写的代码永远不亏。
    """
    console.rule("[bold cyan]第 1 步：加载为 Document")

    articles = load_articles(DATA_DIR)
    docs = [
        Document(
            page_content=a.content,
            metadata={"article_id": a.id, "title": a.title, "tags": a.tags},
        )
        for a in articles
    ]
    console.print(f"加载 {len(docs)} 篇文章，第一篇的 metadata：{docs[0].metadata}\n")
    return docs


def step_2_split(docs: list[Document]) -> list[Document]:
    """第 2 步：切片 —— MarkdownHeaderTextSplitter 对照我们手写的 chunker。

    它和我们 02 模块手写的「按标题切 + 保留标题路径」思路完全一致：
    按 ## 切分，并把标题写进每个切片的 metadata。
    """
    console.rule("[bold cyan]第 2 步：按标题切片")

    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("##", "section"), ("###", "subsection")],
        strip_headers=False,  # 标题保留在正文里（参与 embedding，我们手写版的经验）
    )

    chunks: list[Document] = []
    for doc in docs:
        for piece in splitter.split_text(doc.page_content):
            # 切片继承文章级 metadata，再叠加切分器产出的标题 metadata
            piece.metadata.update(doc.metadata)
            chunks.append(piece)

    console.print(f"共切出 {len(chunks)} 个 chunk")
    sample = chunks[5]
    console.print(f"示例 chunk metadata：{sample.metadata}")
    console.print(f"[dim]{sample.page_content[:80]}……[/dim]\n")
    return chunks


def step_3_vector_store(chunks: list[Document]) -> QdrantVectorStore:
    """第 3 步：向量化 + 入库，一个方法搞定。

    from_documents 内部做了我们 02 模块手写的全部事情：
    创建 collection -> 批量 embed_documents -> upsert（含 metadata）。
    """
    console.rule("[bold cyan]第 3 步：向量入库（QdrantVectorStore）")

    vector_store = QdrantVectorStore.from_documents(
        documents=chunks,
        embedding=FastEmbedEmbeddings(),  # 我们自己实现的 Embeddings 组件！
        location=":memory:",              # 教学用内存模式；实战换成 url="http://..."
        collection_name="blog_lc",
    )

    # 先用底层检索 API 验证一下（带分数）
    hits = vector_store.similarity_search_with_score("前端构建太慢怎么优化", k=3)
    console.print("similarity_search_with_score 验证：")
    for doc, score in hits:
        console.print(f"  score={score:.3f}  《{doc.metadata['title'][:18]}》")
    console.print()
    return vector_store


def step_4_rag_chain(vector_store: QdrantVectorStore) -> None:
    """第 4 步：retriever + 管道，拼出完整 RAG 链。

    as_retriever() 把向量库变成 Runnable —— 于是它能进管道。
    数据流：问题(str) -> retriever -> list[Document] -> 填进模板 -> 模型 -> 答案
    """
    console.rule("[bold cyan]第 4 步：完整 RAG 管道（需要 LLM Key）")

    from lc_client import get_chat_model  # 放在函数内：前三步离线也能跑

    retriever = vector_store.as_retriever(search_kwargs={"k": 4})

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "你是技术博客AI助手。严格根据 <context> 中的内容回答，"
                "没有相关内容就说「博客中没有找到」。回答不超过150字，结尾列出来源文章标题。",
            ),
            ("user", "<context>\n{context}\n</context>\n\n问题：{question}"),
        ]
    )

    def format_docs(docs: list[Document]) -> str:
        """把检索到的 Document 拼成上下文字符串（带文章标题）。"""
        return "\n\n".join(
            f"出自《{d.metadata['title']}》：\n{d.page_content}" for d in docs
        )

    # 管道组装：dict 的每个 value 都是 Runnable/函数，并行求值后填进模板
    chain = (
        {
            "context": retriever | format_docs,   # 问题 -> 检索 -> 拼接上下文
            "question": lambda x: x,              # 问题原样传递
        }
        | prompt
        | get_chat_model()
        | StrOutputParser()
    )

    question = "useEffect 为什么在开发环境执行两次？"
    console.print(f"提问：[bold]{question}[/bold]")
    answer = chain.invoke(question)
    console.print(Panel(answer, title="RAG 管道回答", border_style="green"))


if __name__ == "__main__":
    documents = step_1_load_documents()
    chunk_docs = step_2_split(documents)
    store = step_3_vector_store(chunk_docs)
    step_4_rag_chain(store)
    console.print("\n[bold green]本章完成！下一章用 create_agent 一行构建 Agent。[/bold green]")
