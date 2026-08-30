"""
db_logger.py - SQLite 기반 실시간 매매일지 및 손익 통계 관리 모듈
===========================================================================
"""

import os
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "trade_history.db")


class TradeDBLogger:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path, timeout=10.0)

    def _init_db(self):
        """테이블 스키마 생성 및 초기화"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trade_date TEXT NOT NULL,
                        code TEXT NOT NULL,
                        name TEXT NOT NULL,
                        buy_time TEXT NOT NULL,
                        buy_price REAL NOT NULL,
                        buy_qty INTEGER NOT NULL,
                        buy_amount REAL NOT NULL,
                        buy_reason TEXT,
                        trade_intensity REAL DEFAULT 0.0,
                        is_aggressive INTEGER DEFAULT 0,
                        sell_time TEXT,
                        sell_price REAL,
                        sell_qty INTEGER,
                        sell_amount REAL,
                        sell_reason TEXT,
                        profit_loss REAL,
                        return_rate REAL,
                        status TEXT DEFAULT 'HOLDING'
                    );
                """)
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date);")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_code_status ON trades(code, status);")
                conn.commit()
            logger.info(f"📊 [TradeDB] 데이터베이스 연결 및 초기화 완료: {self.db_path}")
        except Exception as e:
            logger.error(f"❌ [TradeDB] 초기화 실패: {e}")

    def log_buy(self, code: str, name: str, buy_price: float, buy_qty: int,
                buy_reason: str, trade_intensity: float = 0.0, is_aggressive: bool = False) -> int:
        """매수 체결 기록 저장"""
        now = datetime.now()
        trade_date = now.strftime("%Y-%m-%d")
        buy_time = now.strftime("%Y-%m-%d %H:%M:%S")
        buy_amount = float(buy_price * buy_qty)

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO trades (
                        trade_date, code, name, buy_time, buy_price, buy_qty,
                        buy_amount, buy_reason, trade_intensity, is_aggressive, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'HOLDING')
                """, (
                    trade_date, code, name, buy_time, buy_price, buy_qty,
                    buy_amount, buy_reason, trade_intensity, 1 if is_aggressive else 0
                ))
                conn.commit()
                trade_id = cursor.lastrowid
                logger.info(f"💾 [TradeDB] 매수 기록 저장 완료 (ID: {trade_id}, 종목: {name}({code}), {buy_qty}주 @ {buy_price:,.0f}원)")
                return trade_id
        except Exception as e:
            logger.error(f"❌ [TradeDB] 매수 기록 저장 실패 ({code}): {e}")
            return -1

    def log_sell(self, code: str, sell_price: float, sell_qty: int, sell_reason: str) -> dict:
        """매도 체결 기록 및 실현손익 계산/저장"""
        now = datetime.now()
        sell_time = now.strftime("%Y-%m-%d %H:%M:%S")
        sell_amount = float(sell_price * sell_qty)

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # 현재 HOLDING 상태인 가장 최근 매수 건 조회
                cursor.execute("""
                    SELECT id, buy_price, buy_qty, buy_amount, name
                    FROM trades
                    WHERE code = ? AND status = 'HOLDING'
                    ORDER BY id DESC LIMIT 1
                """, (code,))
                row = cursor.fetchone()

                if not row:
                    logger.warning(f"⚠️ [TradeDB] HOLDING 중인 매수 기록을 찾을 수 없음 ({code}). 단독 매도로 기록합니다.")
                    cursor.execute("""
                        INSERT INTO trades (
                            trade_date, code, name, buy_time, buy_price, buy_qty,
                            buy_amount, sell_time, sell_price, sell_qty, sell_amount,
                            sell_reason, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CLOSED')
                    """, (
                        now.strftime("%Y-%m-%d"), code, code, sell_time, 0, 0, 0,
                        sell_time, sell_price, sell_qty, sell_amount, sell_reason
                    ))
                    conn.commit()
                    return {"profit_loss": 0.0, "return_rate": 0.0}

                trade_id = row['id']
                buy_price = row['buy_price']
                name = row['name']

                # 수수료/세금 대략 감안 실현손익 산출 (매수가 대비)
                if buy_price > 0:
                    profit_loss = (sell_price - buy_price) * sell_qty
                    return_rate = ((sell_price - buy_price) / buy_price) * 100
                else:
                    profit_loss = 0.0
                    return_rate = 0.0

                cursor.execute("""
                    UPDATE trades SET
                        sell_time = ?,
                        sell_price = ?,
                        sell_qty = ?,
                        sell_amount = ?,
                        sell_reason = ?,
                        profit_loss = ?,
                        return_rate = ?,
                        status = 'CLOSED'
                    WHERE id = ?
                """, (
                    sell_time, sell_price, sell_qty, sell_amount,
                    sell_reason, profit_loss, return_rate, trade_id
                ))
                conn.commit()

                pnl_str = f"{profit_loss:+,.0f}원 ({return_rate:+.2f}%)"
                logger.info(f"💾 [TradeDB] 매도 손익 정산 완료 (ID: {trade_id}, 종목: {name}, 손익: {pnl_str})")
                return {
                    "trade_id": trade_id,
                    "name": name,
                    "profit_loss": profit_loss,
                    "return_rate": return_rate
                }
        except Exception as e:
            logger.error(f"❌ [TradeDB] 매도 기록 저장 실패 ({code}): {e}")
            return {"profit_loss": 0.0, "return_rate": 0.0}

    def get_daily_summary(self, trade_date: str = None) -> dict:
        """특정 일자의 매매 통계 (승률, 총 손익, 매매 건수) 산출"""
        if not trade_date:
            trade_date = datetime.now().strftime("%Y-%m-%d")

        try:
            with self._get_connection() as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT
                        COUNT(*) as total_trades,
                        SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) as win_trades,
                        SUM(CASE WHEN profit_loss <= 0 THEN 1 ELSE 0 END) as loss_trades,
                        SUM(profit_loss) as total_pnl,
                        AVG(return_rate) as avg_return,
                        SUM(buy_amount) as total_buy_volume
                    FROM trades
                    WHERE trade_date = ? AND status = 'CLOSED'
                """, (trade_date,))
                res = cursor.fetchone()

                total_trades = res['total_trades'] or 0
                win_trades = res['win_trades'] or 0
                loss_trades = res['loss_trades'] or 0
                total_pnl = res['total_pnl'] or 0.0
                avg_return = res['avg_return'] or 0.0
                total_buy_vol = res['total_buy_volume'] or 0.0

                win_rate = (win_trades / total_trades * 100) if total_trades > 0 else 0.0

                return {
                    "date": trade_date,
                    "total_trades": total_trades,
                    "win_trades": win_trades,
                    "loss_trades": loss_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "avg_return": avg_return,
                    "total_buy_volume": total_buy_vol
                }
        except Exception as e:
            logger.error(f"❌ [TradeDB] 일일 통계 산출 실패: {e}")
            return {}

    def print_daily_summary(self, trade_date: str = None):
        """일일 통계를 콘솔/로그에 보기 좋게 출력"""
        summary = self.get_daily_summary(trade_date)
        if not summary:
            return

        date_str = summary.get('date', '')
        total = summary.get('total_trades', 0)
        win = summary.get('win_trades', 0)
        loss = summary.get('loss_trades', 0)
        win_rate = summary.get('win_rate', 0.0)
        pnl = summary.get('total_pnl', 0.0)
        avg_ret = summary.get('avg_return', 0.0)

        logger.info("=" * 60)
        logger.info(f" 📊 [{date_str}] 자동매매 성과 일일 리포트")
        logger.info(f" 📌 총 완료 매매: {total}건 (승: {win}건 / 패: {loss}건)")
        logger.info(f" 🎯 승률(Win Rate): {win_rate:.1f}%")
        logger.info(f" 💰 총 실현손익: {pnl:+,.0f}원 (평균 수익률: {avg_ret:+.2f}%)")
        logger.info("=" * 60)
