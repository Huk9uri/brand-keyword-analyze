"""동일한 분석 결과로 모델별 비용과 검증 결과를 기록한다. 품질 승인은 자동화하지 않는다."""
import json
import shutil
import time
import hashlib
from pathlib import Path
from .summary import generate
from .workflow import write

# 2026-09-16 공식 가격, USD / 100만 토큰. 캐시 할인 제외 보수적 추정.
RATES={'gpt-4.1-mini':(0.40,1.60),'gpt-5-mini':(0.25,2.00),'gpt-5.6-luna':(0.20,1.20)}


def cost(model,usage):
    if not usage or 'input_tokens' not in usage or 'output_tokens' not in usage:return None
    incoming,outgoing=RATES[model]
    # output_tokens는 추론 토큰을 포함하므로 별도로 더하지 않는다.
    return (usage['input_tokens']*incoming+usage['output_tokens']*outgoing)/1_000_000


def compare(root,key,store_code=None):
    root=Path(root)
    if not key:raise ValueError('OPENAI_API_KEY_REQUIRED')
    results=[]
    for model in RATES:
        target=root/'model-comparison'/model
        target.mkdir(parents=True,exist_ok=True)
        for name in ('status.json','quality.json','results.json','changes.json','registry.json','sales.json','unmapped-menus.json','observations.json'):
            if (root/name).exists():shutil.copyfile(root/name,target/name)
            elif (target/name).exists():(target/name).unlink()
        started=time.monotonic()
        try:
            receipt=generate(target,model,key,store_code=store_code)
            summary_root=target if store_code is None else target/'store-summaries'/hashlib.sha256(store_code.encode()).hexdigest()[:16]
            row=dict(model=model,status=receipt['status'],usage=receipt['usage'],estimated_usd=cost(model,receipt['usage']),
                     human_quality_review='PENDING',summary=str(summary_root/'summary.md'))
        except Exception as exc:
            row=dict(model=model,status='FAILED',error_type=type(exc).__name__)
        row['elapsed_seconds']=round(time.monotonic()-started,3)
        results.append(row)
        name='model-comparison.json' if store_code is None else 'model-comparison-store-'+hashlib.sha256(store_code.encode()).hexdigest()[:16]+'.json'
        write(root,name,dict(price_date='2026-09-16',store_code=store_code,selected_model=None,results=results))
    return results
