# 내 PC에서 돌리기

발행 단계는 사용자 PC에서만 돌아갑니다. 네이버가 데이터센터 IP의 로그인을 막기 때문입니다.
사진 폴더도 PC에 있으니 4번 단계부터는 여기서 하는 편이 편합니다.

## 1. 준비 (한 번만)

파워셸을 열고 순서대로 실행합니다.

```powershell
# 파이썬이 없으면 python.org 에서 3.11 이상 설치 (설치 시 'Add to PATH' 체크)
python --version

# 저장소 받기
cd $HOME\Desktop\Freelancer
git clone https://github.com/SBJarvis0315/jarvis.git
cd jarvis
git checkout claude/naver-blog-content-automation-dgzgvb

# 필요한 것 설치
pip install playwright python-docx
python -m playwright install chromium
```

## 2. 네이버 로그인 (한 번만)

```powershell
cd naver-blog-automation
python publish\editor.py login
```

크롬 창이 열립니다. **직접 로그인**하시고, 끝나면 터미널로 돌아와 엔터를 누르세요.
로그인 세션은 `work\browser-profile` 에 남아 다음부터는 다시 로그인하지 않습니다.

이 폴더에는 로그인 쿠키가 들어 있습니다. 깃에 올라가지 않게 해뒀지만, 남에게 주지 마세요.

## 3. 에디터 구조 뜨기 (한 번만)

```powershell
python publish\editor.py inspect --blog niceolive
```

글쓰기 화면이 열립니다. 로딩이 끝나면 **우측 상단 '템플릿' 버튼을 눌러 '내 템플릿' 탭까지
띄워둔 다음** 터미널에서 엔터를 누르세요.

`work\inspect.json` 과 스크린샷이 생깁니다. **두 파일을 채팅에 올려주시면** 제가
`selectors.json` 을 채워 발행 단계를 완성합니다.

## 4. 사진 카탈로그 (한 번만, 사진이 늘면 다시)

```powershell
python publish\images.py catalog --dir "$HOME\Desktop\Freelancer\두청한의원(스마트브랜딩)\사진" --out work\catalog.json
python publish\images.py todo --catalog work\catalog.json
```

설명이 없는 사진 목록이 뜹니다. 이 상태에서 저를 로컬 세션으로 부르시면
제가 사진을 하나씩 열어보고 설명을 채웁니다. 한 번 해두면 계속 재사용됩니다.

## 5. 원고 한 건 처리

```powershell
python publish\docxparse.py 원고.docx --out work\ --heading-lines 1
python publish\related.py index --blog aoske551 --cache work\aoske551.json
python publish\related.py pick --cache work\aoske551.json --keyword 3차신경통 --count 2 --json work\related.json
python publish\plan.py --doc work\doc.json --template clients\ducheong\template.json --keyword 3차신경통 --related work\related.json --out work\plan.json
python publish\images.py assign --plan work\plan.json --catalog work\catalog.json --out work\assign.json
python publish\images.py stock --assign work\assign.json --out work\media\
python publish\editor.py publish --plan work\plan.json --assign work\assign.json
```

`related.py index` 는 처음 한 번만 돌리면 됩니다. 755건을 캐시해 둡니다.

## 주의

- 발행은 **임시저장까지만** 합니다. 최종 발행 버튼은 눈으로 확인하고 직접 누르세요.
- 네이버가 화면 구조를 바꾸면 3번을 다시 돌려 셀렉터를 갱신해야 합니다.
