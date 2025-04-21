#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
데이터베이스 스키마 확인 스크립트
"""

import psycopg2
import sys

DB_URL = "postgresql://casino_user:secure_password@localhost:5432/casino_db"

def check_table_schema(table_name):
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(f"SELECT column_name, data_type FROM information_schema.columns WHERE table_name = '{table_name}' ORDER BY ordinal_position")
        rows = cur.fetchall()
        
        print(f"\n{table_name.upper()} 테이블 스키마: ({len(rows)}개 컬럼)")
        for row in rows:
            print(f"  {row[0]} - {row[1]}")
        
        conn.close()
    except Exception as e:
        print(f"오류 발생: {str(e)}")

if __name__ == "__main__":
    check_table_schema("wallets")
    check_table_schema("transactions")
    check_table_schema("aml_risk_profiles")
    check_table_schema("aml_alerts") 