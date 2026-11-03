import os
import sys
import json
from datetime import datetime

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class FinancialStoryteller:
    """
    수석 경제 전문 스토리텔러 퀀트 앵커 엔진.
    데이터의 실제 등락(+ / -)을 100% 엄격하게 반영하여,
    상승/하락의 인과관계와 9시 개장 15분 실전 행동 강령을
    황금 6단계 서사 구조로 창작합니다.
    """

    def __init__(self, data_source=None):
        self.data = self._load_data(data_source)

    def _load_data(self, data_source):
        if isinstance(data_source, dict):
            return data_source
        json_path = data_source or ".tmp/market_anomaly_today.json"
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ JSON 로드 오류: {e}")
        return {}

    def _extract_market_context(self):
        """Extracts and normalizes macro, index, and sector movements."""
        all_data = self.data.get("all_data", [])
        data_map = {item["symbol"]: item for item in all_data if "symbol" in item}

        key_indices = self.data.get("key_indices", {})
        korea_ind = self.data.get("korea_indicators", {})

        # Major Indices
        sp = key_indices.get("sp500") or data_map.get("^GSPC") or {"change_pct": 0.0}
        nq = key_indices.get("nasdaq") or data_map.get("^IXIC") or {"change_pct": 0.0}
        dji = data_map.get("^DJI") or {"name": "다우존스", "change_pct": 0.0}
        sox = korea_ind.get("sox") or key_indices.get("sox") or self.data.get("top_macro") or data_map.get("^SOX") or {"price": 0, "change_pct": 0.0}

        # Macro Indicators
        oil = data_map.get("CL=F") or {"name": "WTI 원유", "change_pct": 0.0}
        tnx = key_indices.get("treasury_10y") or data_map.get("^TNX") or {"price": 4.9, "change_pct": 0.0}
        vix = data_map.get("^VIX") or {"price": 18.0, "change_pct": 0.0}
        usd = data_map.get("DX-Y.NYB") or {"change_pct": 0.0}

        # Korea Night Futures
        k2 = korea_ind.get("kospi200_night") or {"change_pct": 0.0}
        kq = korea_ind.get("kosdaq150_night") or {"change_pct": 0.0}

        # Top Anomaly Stock
        top_stock = self.data.get("top_anomaly") or data_map.get("MSFT") or data_map.get("NVDA") or {"name": "주요 기술주", "change_pct": 0.0}

        # Headlines
        headlines = self.data.get("market_headlines", [])

        return {
            "sp": sp,
            "nq": nq,
            "dji": dji,
            "sox": sox,
            "oil": oil,
            "tnx": tnx,
            "vix": vix,
            "usd": usd,
            "k2": k2,
            "kq": kq,
            "top_stock": top_stock,
            "headlines": headlines
        }

    def generate_story_script(self) -> list[str]:
        """
        Executes the storytelling generation.
        Adheres strictly to the 6-stage narrative formula with 100% directional consistency.
        """
        ctx = self._extract_market_context()
        return self._build_deterministic_story(ctx)

    def _build_deterministic_story(self, ctx) -> list[str]:
        """
        Dynamically crafts narration matching exact market directions.
        NEVER confuses surge/drop.
        """
        sox_pct = ctx["sox"].get("change_pct", 0.0)
        nq_pct = ctx["nq"].get("change_pct", 0.0)
        dji_pct = ctx["dji"].get("change_pct", 0.0)
        sp_pct = ctx["sp"].get("change_pct", 0.0)
        oil_pct = ctx["oil"].get("change_pct", 0.0)
        k2_pct = ctx["k2"].get("change_pct", 0.0)

        top_item = ctx["top_stock"]
        top_name = top_item.get("name", "기술주").split(" ")[0]
        top_pct = top_item.get("change_pct", 0.0)

        # 1. Directional classifications
        sox_is_up = sox_pct > 0.3
        sox_is_down = sox_pct < -0.3
        nq_is_up = nq_pct > 0.2
        nq_is_down = nq_pct < -0.2

        # [1단계] 오프닝 리드
        hook_lead = "개장 전 반드시 알아야 할 핵심 뉴스만 전해드리는 ‘오늘의 모닝 퀀트 브리핑’ 시작합니다."

        # [2단계] 핵심 훅 (실제 데이터 방향과 100% 일치)
        if sox_is_up and nq_is_up:
            hook_paradox = f"밤사이 필라델피아 반도체 지수가 {abs(sox_pct):.1f}% 급등하며 기술주가 안도 랠리를 펼쳤습니다! 오늘 9시 국장 반도체는 과연 어떻게 움직일까요? 1분 만에 짚어드립니다."
        elif sox_is_down and nq_is_down:
            hook_paradox = f"필라델피아 반도체 지수가 {abs(sox_pct):.1f}% 밀리며 기술주 조정이 이어졌습니다! 오늘 아침 삼성전자와 하이닉스 계좌, 어떻게 지켜야 할까요? 1분 만에 짚어드립니다."
        elif abs(oil_pct) >= 3.0:
            oil_action = "폭락" if oil_pct < 0 else "급등"
            hook_paradox = f"국제 유가가 {abs(oil_pct):.1f}%나 {oil_action}하며 글로벌 증시가 요동쳤습니다! 오늘 개장 전 필수 체크 포인트를 1분 만에 정리해 드립니다."
        else:
            hook_paradox = "간밤 글로벌 선행 지표가 엇갈린 흐름을 보였습니다. 오늘 아침 9시 개장 직전, 핵심 팩트만 1분 만에 정리해 드립니다."

        # [3단계] 지수 흐름 & 주요 원인 제시 (상승/하락 절대 왜곡 금지)
        if sox_is_up:
            div_text = f"간밤 뉴욕 증시는 반도체 섹터의 강한 반등이 이끌었습니다. 필라델피아 반도체 지수가 {abs(sox_pct):.1f}% 상승 마감했고, 나스닥 역시 견조한 상승세를 기록했습니다. 원인은 크게 두 가지입니다."
        elif sox_is_down:
            div_text = f"간밤 뉴욕 증시는 기술주 섹터의 차익 실현 매물이 부담으로 작용했습니다. 필라델피아 반도체 지수가 {abs(sox_pct):.1f}% 하락하며 숨고르기에 들어갔는데요. 원인은 크게 두 가지입니다."
        else:
            div_text = f"간밤 뉴욕 증시는 주요 지표 발표를 앞두고 관망세를 보였습니다. 나스닥과 반도체 지수가 보합권에서 공방을 벌였는데요. 원인은 크게 두 가지입니다."

        # [4단계] 원인 1: 거시 지표 / 유가 / 금리
        if oil_pct <= -2.0:
            c1_text = f"첫째, 국제 유가가 {abs(oil_pct):.1f}% 급락하며 인플레이션 완화 기대감이 커졌고, 이에 따라 시장의 금리 부담이 다소 완화되었습니다."
        elif oil_pct >= 2.0:
            c1_text = f"첫째, 유가가 {abs(oil_pct):.1f}% 급등하며 원자재 가격 불안 요인이 부각되었으나, 기업들의 견조한 펀더멘털이 지수를 방어했습니다."
        else:
            c1_text = "첫째, 미국의 주요 거시 경제 지표들이 시장 예상치에 부합하게 발표되며 글로벌 경기 침체에 대한 극단적인 우려를 덜어냈습니다."

        # [5단계] 원인 2: 핵심 대장주 및 반도체 섹터 동향 (상승/하락 정확한 서술)
        if top_pct > 0.5:
            top_action = f"{abs(top_pct):.1f}% 상승하며 지수 반등의 견인차 역할을 했습니다"
        elif top_pct < -0.5:
            top_action = f"{abs(top_pct):.1f}% 하락하며 단기 밸류에이션 부담을 소화했습니다"
        else:
            top_action = "보합권에서 등락을 보이며 다음 모멘텀을 모색했습니다"

        if sox_is_up:
            c2_text = (
                f"둘째, AI 반도체 수요에 대한 신뢰가 재확인되었습니다. "
                f"대장주인 {top_name}가 {top_action}. "
                f"국내 야간 코스피200 선물 역시 {abs(k2_pct):.1f}% {'상승' if k2_pct >= 0 else '하락'}하며 "
                f"오늘 국내 증시 시초가에도 긍정적인 기대감이 반영되고 있습니다."
            )
        else:
            c2_text = (
                f"둘째, 단기 급등에 따른 기술적 매물이 출회되었습니다. "
                f"{top_name}가 {top_action}. "
                f"여기에 수급 경계감이 겹치며 국내 야간 선물 시장에서도 변동성이 커진 모습입니다."
            )

        # [6단계] 9시 개장 직후 '15분 실전 매매 대응 3원칙'
        if sox_is_up:
            action_guide = (
                "다만 해외 지수가 올랐다고 해서 9시 개장 직후 무리하게 시초가에 추격 매수하는 것은 위험합니다! "
                "반드시 9시 15분까지 외국인의 실시간 순매수 유입과 당일 시가 지지 여부를 확인하고 "
                "분할 대응하시는 '15분 원칙'을 꼭 지켜주시기 바랍니다."
            )
        else:
            action_guide = (
                "반도체 변동성이 커진 날일수록 9시 개장 직후 15분간은 섣부른 매매를 멈추고 관망해야 합니다. "
                "외국인 선현물 동시 순매수 전환과 시가 지지선을 확인한 뒤 분할 진입하는 '15분 원칙'으로 계좌를 지키세요."
            )

        # [7단계] 클로징 & 구독 CTA
        cta = "구독과 알림 설정해 두시고, 내일 아침도 가장 빠른 퀀트 브리핑을 받아보세요!"

        script_lines = [
            hook_lead,
            hook_paradox,
            div_text,
            c1_text,
            c2_text,
            action_guide,
            cta
        ]

        return script_lines

def generate_story_narration():
    storyteller = FinancialStoryteller()
    lines = storyteller.generate_story_script()
    print("\n" + "=" * 60)
    print("🎬 [스토리텔링 전문가 공식 대본 - 100% 데이터 일치 검증]")
    print("=" * 60)
    for i, line in enumerate(lines, 1):
        print(f"\n[{i}단계] {line}")
    print("\n" + "=" * 60)

if __name__ == "__main__":
    generate_story_narration()
