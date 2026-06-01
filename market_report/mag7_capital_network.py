from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapitalRelation:
    investor: str
    investor_ticker: str
    target: str
    target_ticker: str
    relation_type: str
    disclosed_value: str
    disclosed_at: str
    source: str
    source_url: str
    confidence: str
    note: str
    themes: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class AggregateCapitalDisclosure:
    investor: str
    investor_ticker: str
    category: str
    disclosed_value: str
    disclosed_at: str
    source: str
    source_url: str
    note: str


@dataclass(frozen=True)
class Mag7CapitalNetwork:
    summary: str
    relations: tuple[CapitalRelation, ...]
    aggregate_disclosures: tuple[AggregateCapitalDisclosure, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


def build_mag7_capital_network() -> Mag7CapitalNetwork:
    relations = (
        CapitalRelation(
            investor="Microsoft",
            investor_ticker="MSFT",
            target="OpenAI",
            target_ticker="PRIVATE",
            relation_type="战略股权与云合作",
            disclosed_value="主要股东；金额未在最新公告中披露",
            disclosed_at="2026-04-27",
            source="Microsoft 官方公告",
            source_url="https://blogs.microsoft.com/blog/2026/04/27/the-next-phase-of-the-microsoft-openai-partnership/",
            confidence="高",
            note="Microsoft 仍为 OpenAI 主要云合作伙伴，并继续作为主要股东参与 OpenAI 增长。该关系同时映射 Azure AI 基础设施需求。",
            themes=("AI模型", "Azure", "云基础设施"),
        ),
        CapitalRelation(
            investor="Amazon",
            investor_ticker="AMZN",
            target="Anthropic",
            target_ticker="PRIVATE",
            relation_type="少数股权与云合作",
            disclosed_value="追加投资 5B 美元；未来最高追加 20B 美元，另有既有投资 8B 美元",
            disclosed_at="2026-04-24",
            source="Amazon 官方公告",
            source_url="https://www.aboutamazon.com/news/company-news/amazon-invests-additional-5-billion-anthropic-ai?hl=en-US",
            confidence="高",
            note="Anthropic 承诺未来十年在 AWS 技术上投入超过 100B 美元，并使用 Trainium 系列芯片。关系同时反映模型、云收入和自研芯片闭环。",
            themes=("AI模型", "AWS", "Trainium"),
        ),
        CapitalRelation(
            investor="NVIDIA",
            investor_ticker="NVDA",
            target="CoreWeave",
            target_ticker="CRWV",
            relation_type="上市股权与 AI 云合作",
            disclosed_value="投资 2B 美元，认购价 87.20 美元/股",
            disclosed_at="2026-01-26",
            source="NVIDIA 官方公告",
            source_url="https://nvidianews.nvidia.com/news/nvidia-and-coreweave-strengthen-collaboration-to-accelerate-buildout-of-ai-factories",
            confidence="高",
            note="CoreWeave 计划扩展超过 5GW AI factories。该连接反映 GPU 需求、AI 云资本开支与数据中心电力需求之间的联动。",
            themes=("AI云", "数据中心", "电力"),
        ),
        CapitalRelation(
            investor="NVIDIA",
            investor_ticker="NVDA",
            target="Coherent",
            target_ticker="COHR",
            relation_type="上市股权与光通信合作",
            disclosed_value="投资 2B 美元",
            disclosed_at="2026-03-02",
            source="NVIDIA 官方公告",
            source_url="https://nvidianews.nvidia.com/news/nvidia-and-coherent-announce-strategic-partnership-to-develop-optics-technology-to-scale-next-generation-data-center-architecture",
            confidence="高",
            note="资金用于研发、产能与美国制造扩张。该连接指向 AI 数据中心光互连与先进封装扩容。",
            themes=("光通信", "AI基础设施", "美国制造"),
        ),
        CapitalRelation(
            investor="NVIDIA",
            investor_ticker="NVDA",
            target="Lumentum",
            target_ticker="LITE",
            relation_type="上市股权与光通信合作",
            disclosed_value="投资 2B 美元",
            disclosed_at="2026-03-02",
            source="NVIDIA 官方公告",
            source_url="https://nvidianews.nvidia.com/news/nvidia-announces-strategic-partnership-with-lumentum-to-develop-state-of-the-art-optics-technology",
            confidence="高",
            note="合作覆盖先进激光器、未来产能和新晶圆厂。该连接是 AI 光模块产业链需求扩散的可核验信号。",
            themes=("光通信", "激光器", "AI基础设施"),
        ),
        CapitalRelation(
            investor="NVIDIA",
            investor_ticker="NVDA",
            target="Marvell Technology",
            target_ticker="MRVL",
            relation_type="上市股权与定制芯片合作",
            disclosed_value="投资 2B 美元",
            disclosed_at="2026-03-31",
            source="NVIDIA 官方公告",
            source_url="https://nvidianews.nvidia.com/news/nvidia-ai-ecosystem-expands-as-marvell-joins-forces-through-nvlink-fusion",
            confidence="高",
            note="双方围绕 NVLink Fusion、定制 XPU、scale-up networking 和 silicon photonics 合作。",
            themes=("半导体", "网络互连", "光通信"),
        ),
        CapitalRelation(
            investor="NVIDIA",
            investor_ticker="NVDA",
            target="IREN",
            target_ticker="IREN",
            relation_type="股权投资权利与 AI 数据中心合作",
            disclosed_value="未来五年可投资最高 2.1B 美元",
            disclosed_at="2026-05-07",
            source="NVIDIA 官方公告",
            source_url="https://nvidianews.nvidia.com/news/nvidia-and-iren-announce-strategic-partnership-to-accelerate-deployment-of-up-to-5-gigawatts-of-ai-infrastructure",
            confidence="高",
            note="IREN 向 NVIDIA 授予最多 3000 万股认购权，合作目标为最高 5GW AI 基础设施部署。该项仍包含条件约束。",
            themes=("AI云", "数据中心", "电力"),
        ),
    )
    aggregate_disclosures = (
        AggregateCapitalDisclosure(
            investor="Alphabet",
            investor_ticker="GOOGL",
            category="非上市股权证券",
            disclosed_value="账面价值 64.1B 美元",
            disclosed_at="2025-12-31",
            source="Alphabet 2025 Form 10-K",
            source_url="https://www.sec.gov/Archives/edgar/data/1652044/000165204426000018/goog-20251231.htm",
            note="财报披露聚合账面价值，但未公开完整底层名单。不能将该金额直接解释为某一 AI 项目的持仓。",
        ),
    )
    return Mag7CapitalNetwork(
        summary=(
            f"当前清单收录 {len(relations)} 条可核验资本连接和 {len(aggregate_disclosures)} 条聚合披露。"
            "重点观察 MAG7 资本是否沿 AI 模型、云平台、光通信、定制芯片和数据中心电力链扩散。"
        ),
        relations=relations,
        aggregate_disclosures=aggregate_disclosures,
        warnings=(
            "该图谱是公开披露关系的可识别下限，不是 MAG7 完整证券持仓表。",
            "私募投资、子公司投资和商业合作不一定逐项披露；战略合作也不等同于已确认股权持仓。",
            "Apple、Meta 和 Tesla 暂未出现在首批具名资本连接中，不表示其不存在未逐项披露的投资或产业链关系。",
            "关系记录仅用于产业链研究与事件复核，不构成交易建议。",
        ),
    )
