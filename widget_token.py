"""Local administrator helper for the read-only widget token."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from widget_api import WidgetTokenFile, read_json

def main():
    parser=argparse.ArgumentParser(description='生成/查看状态/撤销当前学校账号的小组件只读凭证')
    parser.add_argument('action',choices=('status','rotate','revoke'))
    parser.add_argument('--data-dir',default=os.getenv('SSWS_DATA_DIR','data'))
    args=parser.parse_args();directory=Path(args.data_dir)
    config=read_json(directory/'webui_config.json')
    if not config.get('sdut_user'):raise SystemExit('先在网页中配置学校账号')
    account_key=hashlib.sha256(config['sdut_user'].encode()).hexdigest()[:24]
    api=WidgetTokenFile(directory/'webui_widget_token.json')
    result=api.revoke() if args.action=='revoke' else getattr(api,args.action)(account_key)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
