"""Gmail 발송 전용 OAuth 최초 로그인. 앱 비밀번호는 사용하지 않는다."""
import argparse
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client-file',type=Path,default=Path('.secrets/gmail-client.json'))
    parser.add_argument('--token-file',type=Path,default=Path('.secrets/gmail-token.json'))
    args=parser.parse_args()
    if not args.client_file.exists():
        parser.error('Google Cloud의 데스크톱 앱 OAuth 클라이언트 JSON을 .secrets/gmail-client.json에 저장하세요.')
    from google_auth_oauthlib.flow import InstalledAppFlow
    from .gmail_sender import SCOPE
    flow=InstalledAppFlow.from_client_secrets_file(str(args.client_file),[SCOPE])
    credentials=flow.run_local_server(port=0,access_type='offline',prompt='consent',
        authorization_prompt_message='브라우저에서 발신 Gmail 계정으로 로그인하고 발송 권한을 허용하세요.',
        success_message='Gmail 발송 인증이 완료되었습니다. 이 창을 닫으세요.')
    if not credentials.refresh_token:raise ValueError('REFRESH_TOKEN_REQUIRED')
    args.token_file.parent.mkdir(parents=True,exist_ok=True)
    args.token_file.write_text(credentials.to_json(),encoding='utf-8')
    print('Gmail 인증 저장 완료. 비밀값은 출력하지 않습니다.')


if __name__=='__main__':main()
