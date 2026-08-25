from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from .technical_swing import SwingAssessment, SwingZone, TechnicalSwingReport, nearest_swing_zone


@dataclass(frozen=True)
class PortfolioActionCandidate:
    symbol: str
    action: str
    priority: int
    weight_pct: float
    trigger: str
    rationale: str
    invalidation: str


@dataclass(frozen=True)
class DailyPortfolioReview:
    health_label: str
    health_score: float
    data_cutoff: str
    data_quality: str
    concentration: str
    most_important_action: str
    max_risk: str
    add_candidates: tuple[PortfolioActionCandidate, ...]
    reduce_candidates: tuple[PortfolioActionCandidate, ...]
    hold_summary: str
    caveat: str


def build_daily_portfolio_review(
    positions: Iterable[object],
    portfolio_total_value_gbp: float | None,
    *,
    as_of: date | None = None,
    technical_swing: TechnicalSwingReport | None = None,
) -> DailyPortfolioReview | None:
    items = [item for item in positions if (_num(getattr(item, "quantity", None)) or 0.0) > 0]
    if not items:
        return None
    as_of = as_of or date.today()

    ranked = sorted(items, key=lambda item: _weight(item), reverse=True)
    top_one = _weight(ranked[0])
    top_three = sum(_weight(item) for item in ranked[:3])
    top_symbols = "、".join(str(getattr(item, "symbol", "")) for item in ranked[:3])
    concentration = f"第一大持仓 {top_one:.1f}%；前三大 {top_three:.1f}%（{top_symbols}）"

    source = items[0]
    activity_as_of = _parse_date(getattr(source, "ibkr_activity_as_of", ""))
    trade_as_of = _parse_date(getattr(source, "ibkr_trade_as_of", ""))
    cutoff_parts = []
    if activity_as_of:
        cutoff_parts.append(f"Activity {activity_as_of.isoformat()}")
    if trade_as_of:
        cutoff_parts.append(f"Trade {trade_as_of.isoformat()}")
    data_cutoff = "；".join(cutoff_parts) or "statement 截止日未提供"
    newest_cutoff = max((value for value in (activity_as_of, trade_as_of) if value), default=None)
    age_days = (as_of - newest_cutoff).days if newest_cutoff else None
    stale = age_days is None or age_days > 3
    status = str(getattr(source, "ibkr_data_status", "") or "").strip().lower()
    if stale:
        data_quality = f"过期/不可确认（距最近 statement {age_days if age_days is not None else 'N/A'} 天）"
    elif status == "live":
        data_quality = f"IBKR live；最近 statement {age_days} 天前"
    elif status:
        data_quality = f"{status}；最近 statement {age_days} 天前，时效合格但需核对当日成交"
    else:
        data_quality = f"statement 最近更新 {age_days} 天前；来源状态未标记"

    option_risks = _uncovered_short_puts(items)
    option_underlyings = {risk[0] for risk in option_risks}
    largest_option_risk = max(option_risks, key=lambda item: item[2], default=None)
    total_value = portfolio_total_value_gbp or 0.0
    assignment_ratio = (
        largest_option_risk[2] / total_value * 100
        if largest_option_risk and total_value > 0
        else None
    )

    swing_by_symbol = {
        item.symbol.upper(): item
        for item in (technical_swing.assessments if technical_swing is not None else ())
    }
    add_candidates = [] if stale else _add_candidates(items, option_underlyings, swing_by_symbol)
    reduce_candidates = [] if stale else _reduce_candidates(items, option_risks)
    severe = [item for item in items if _trend_broken(item)]

    score = 10.0
    if stale:
        score -= 3.0
    score -= min(len(severe) * 0.5, 2.5)
    if top_one > 40:
        score -= 1.5
    elif top_one > 25:
        score -= 0.75
    if top_three > 80:
        score -= 1.0
    elif top_three > 65:
        score -= 0.5
    if assignment_ratio is not None and assignment_ratio > 50:
        score -= 1.0
    score = round(max(1.0, min(score, 10.0)), 1)
    health_label = "优秀" if score >= 8.5 else "良好" if score >= 7 else "需要调整" if score >= 5 else "问题严重"

    if stale:
        most_important = "先更新并对账 IBKR/Revolut statement；数据恢复前仅观察，不执行本节加减仓候选。"
    elif assignment_ratio is not None and assignment_ratio > 50 and largest_option_risk:
        most_important = (
            f"先确认 {largest_option_risk[0]} short put 的现金覆盖；潜在接货约占证券持仓 {assignment_ratio:.1f}%，"
            "确认前暂停新增高波动仓位。"
        )
    elif reduce_candidates:
        most_important = (
            f"优先复核 {reduce_candidates[0].symbol}：{reduce_candidates[0].rationale}；"
            "只有触发预设失效条件才执行减仓。"
        )
    elif add_candidates:
        most_important = (
            f"今日只保留 {add_candidates[0].symbol} 为第一加仓观察候选；"
            f"等待 {add_candidates[0].trigger}，不追价。"
        )
    else:
        most_important = "保持仓位，不因单日波动交易；等待价格、事件或投资论文出现明确变化。"

    if largest_option_risk:
        underlying, expiry, notional_gbp, native_text = largest_option_risk
        ratio_text = f"，约占证券持仓 {assignment_ratio:.1f}%" if assignment_ratio is not None else ""
        max_risk = f"{underlying} {expiry} 未覆盖 short put 潜在接货约 £{notional_gbp:,.0f}（{native_text}）{ratio_text}。"
    elif severe:
        max_risk = "趋势/回撤共振：" + "、".join(str(getattr(item, "symbol", "")) for item in severe[:5]) + "。"
    elif top_one > 40:
        max_risk = f"单一持仓集中：{getattr(ranked[0], 'symbol', '')} 占 {top_one:.1f}%。"
    else:
        max_risk = "当前未识别极端单票集中或未覆盖 short put；现金、保证金和完整 Greeks 仍需在券商端核对。"

    action_symbols = {item.symbol for item in add_candidates + reduce_candidates}
    holds = [str(getattr(item, "symbol", "")) for item in ranked if str(getattr(item, "symbol", "")) not in action_symbols]
    hold_summary = "其余持仓维持/观察：" + "、".join(holds[:10]) + ("等。" if len(holds) > 10 else "。")
    caveat = (
        "加减仓候选仅使用当日持仓、价格、趋势、支撑、集中度和开放期权结构；"
        "未验证现金余额、保证金、税务、完整 Greeks 或公司长期估值，不能替代下单前复核。"
    )

    return DailyPortfolioReview(
        health_label=health_label,
        health_score=score,
        data_cutoff=data_cutoff,
        data_quality=data_quality,
        concentration=concentration,
        most_important_action=most_important,
        max_risk=max_risk,
        add_candidates=tuple(add_candidates[:4]),
        reduce_candidates=tuple(reduce_candidates[:4]),
        hold_summary=hold_summary,
        caveat=caveat,
    )


def _add_candidates(
    items: list[object],
    option_underlyings: set[str],
    swing_by_symbol: dict[str, SwingAssessment],
) -> list[PortfolioActionCandidate]:
    candidates: list[PortfolioActionCandidate] = []
    for item in items:
        symbol = str(getattr(item, "symbol", ""))
        drawdown = _num(getattr(item, "drawdown_from_year_peak_pct", None))
        distance_200 = _num(getattr(item, "distance_sma200_pct", None))
        rsi = _num(getattr(item, "rsi14", None))
        if (
            not symbol
            or symbol in option_underlyings
            or drawdown is None
            or drawdown > -5
            or distance_200 is None
            or distance_200 < 0
            or (rsi is not None and rsi > 62)
            or _trend_broken(item)
        ):
            continue
        swing = swing_by_symbol.get(symbol.upper())
        support_zone = (
            nearest_swing_zone(swing.supports, swing.current_price, support=True)
            if swing is not None
            else None
        )
        legacy_support = _nearest_support(item) if support_zone is None else None
        current = _num(getattr(item, "current_price_native", None))
        near_support = _is_near_support(current, support_zone, legacy_support)
        priority = int(min(abs(drawdown), 40) + max(10 - _weight(item), 0) + (8 if near_support else 0))
        if support_zone is not None:
            trigger = (
                f"接近 {_fmt_native_zone(support_zone, item)} 最近技术支撑区"
                f"（强度 {support_zone.score}/100）后企稳"
            )
        elif legacy_support is not None:
            trigger = (
                f"接近 {_fmt_native(legacy_support, item)} 旧版20/60日参考位后企稳"
                "（当日技术支撑区不可用）"
            )
        else:
            trigger = "等待 EMA21/SMA50 附近企稳或重新转强"
        rationale = (
            f"权重 {_weight(item):.1f}%，距年内高点 {drawdown:.1f}%，"
            f"仍高于 SMA200 {distance_200:.1f}%"
            + (f"，RSI {rsi:.0f}" if rsi is not None else "")
        )
        candidates.append(
            PortfolioActionCandidate(
                symbol=symbol,
                action="条件化加仓复核",
                priority=priority,
                weight_pct=_weight(item),
                trigger=trigger,
                rationale=rationale,
                invalidation="跌破 SMA200 或出现公司级论文恶化时取消加仓。",
            )
        )
    return sorted(candidates, key=lambda item: item.priority, reverse=True)


def _reduce_candidates(
    items: list[object],
    option_risks: list[tuple[str, str, float, str]],
) -> list[PortfolioActionCandidate]:
    candidates: list[PortfolioActionCandidate] = []
    risk_by_symbol = {item[0]: item for item in option_risks}
    for item in items:
        symbol = str(getattr(item, "symbol", ""))
        weight = _weight(item)
        drawdown = _num(getattr(item, "drawdown_from_year_peak_pct", None))
        distance_200 = _num(getattr(item, "distance_sma200_pct", None))
        rsi = _num(getattr(item, "rsi14", None))
        reasons = []
        priority = 0
        action = "减仓/退出复核"
        if _trend_broken(item):
            reasons.append("趋势破坏或深度回撤已触发红色阈值")
            priority += 35
        if distance_200 is not None and distance_200 < -3:
            reasons.append(f"低于 SMA200 {abs(distance_200):.1f}%")
            priority += min(int(abs(distance_200)), 25)
        if weight > 15 and not symbol.endswith(".L"):
            reasons.append(f"单票权重 {weight:.1f}% 偏高")
            priority += int(weight)
        if rsi is not None and rsi >= 75 and weight >= 8:
            reasons.append(f"RSI {rsi:.0f} 且仓位较大，可复核止盈")
            priority += 15
        if symbol in risk_by_symbol:
            reasons.append("已有未覆盖 short put 潜在接货，禁止叠加股票风险")
            priority += 40
            action = "不加仓/现金覆盖复核"
        if not reasons:
            continue
        trigger = "确认投资论文恶化或收盘持续位于 SMA200 下方后再执行"
        if symbol in risk_by_symbol:
            trigger = "先确认 short put 全额现金覆盖、到期处理和可接受接货价"
        candidates.append(
            PortfolioActionCandidate(
                symbol=symbol,
                action=action,
                priority=priority,
                weight_pct=weight,
                trigger=trigger,
                rationale="；".join(reasons),
                invalidation=(
                    "重新站回关键趋势并确认论文未变时，取消技术性减仓。"
                    if drawdown is not None
                    else "数据不足时不执行。"
                ),
            )
        )
    return sorted(candidates, key=lambda item: item.priority, reverse=True)


def _uncovered_short_puts(items: list[object]) -> list[tuple[str, str, float, str]]:
    legs = _option_legs(items)
    groups: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for leg in legs:
        if str(leg.get("right") or "").upper() != "P":
            continue
        key = (
            str(leg.get("underlying") or "UNKNOWN"),
            str(leg.get("expiry") or ""),
            str(leg.get("currency") or "").upper(),
        )
        groups.setdefault(key, []).append(leg)
    results = []
    for (underlying, expiry, currency), group in groups.items():
        shorts = [leg for leg in group if (_num(leg.get("signed_contracts")) or 0.0) < 0]
        short_count = sum(abs(_num(leg.get("signed_contracts")) or 0.0) for leg in shorts)
        long_count = sum(max(_num(leg.get("signed_contracts")) or 0.0, 0.0) for leg in group)
        uncovered = max(short_count - long_count, 0.0)
        if uncovered <= 1e-9 or not shorts:
            continue
        short = max(shorts, key=lambda leg: _num(leg.get("strike")) or 0.0)
        strike = _num(short.get("strike")) or 0.0
        multiplier = _num(short.get("multiplier")) or 100.0
        native_notional = strike * uncovered * multiplier
        fx = _leg_fx_to_gbp(short)
        if native_notional > 0 and fx is not None:
            results.append((underlying, expiry, native_notional * fx, f"{currency} {native_notional:,.0f}"))
    return results


def _trend_broken(item: object) -> bool:
    regime = str(getattr(item, "drawdown_regime", "") or "")
    if "趋势破坏" in regime:
        return True
    drawdown = _num(getattr(item, "drawdown_from_year_peak_pct", None))
    red = _num(getattr(item, "red_drawdown_threshold_pct", None)) or 10.0
    distance_200 = _num(getattr(item, "distance_sma200_pct", None))
    return bool(drawdown is not None and drawdown <= -red and distance_200 is not None and distance_200 < 0)


def _nearest_support(item: object) -> float | None:
    current = _num(getattr(item, "current_price_native", None))
    supports = [
        value
        for value in (
            _num(getattr(item, "support_20d_native", None)),
            _num(getattr(item, "support_60d_native", None)),
            _num(getattr(item, "sma50_native", None)),
        )
        if value is not None and value > 0 and (current is None or value <= current * 1.03)
    ]
    return max(supports) if supports else None


def _is_near_support(
    current: float | None,
    zone: SwingZone | None,
    legacy_support: float | None,
) -> bool:
    if current is None or current <= 0:
        return False
    if zone is not None:
        return zone.lower <= current <= zone.upper or (current > zone.upper and current / zone.upper - 1 <= 0.05)
    return bool(legacy_support and abs(current / legacy_support - 1) <= 0.05)


def _fmt_native(value: float, item: object) -> str:
    currency = str(getattr(item, "native_currency", "") or "")
    symbol = "£" if currency == "GBP" else "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def _fmt_native_zone(zone: SwingZone, item: object) -> str:
    currency = str(getattr(item, "native_currency", "") or "")
    symbol = "£" if currency == "GBP" else "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{zone.lower:,.2f}–{zone.upper:,.2f}"


def _option_legs(items: list[object]) -> list[dict[str, object]]:
    for item in items:
        raw = str(getattr(item, "option_legs_json", "") or "")
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [leg for leg in value if isinstance(leg, dict)] if isinstance(value, list) else []
    return []


def _leg_fx_to_gbp(leg: dict[str, object]) -> float | None:
    currency = str(leg.get("currency") or "").upper()
    if currency in {"", "GBP"}:
        return 1.0
    fx = _num(leg.get("fx_rate_to_base"))
    if fx is not None and fx > 0:
        return fx
    for native_key, gbp_key in (
        ("market_value_native", "market_value_gbp"),
        ("net_cash_after_fee_native", "net_cash_after_fee_gbp"),
    ):
        native = _num(leg.get(native_key))
        gbp = _num(leg.get(gbp_key))
        if native is not None and gbp is not None and abs(native) > 1e-9:
            return abs(gbp / native)
    return None


def _parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _weight(item: object) -> float:
    return _num(getattr(item, "weight_pct", None)) or 0.0


def _num(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
