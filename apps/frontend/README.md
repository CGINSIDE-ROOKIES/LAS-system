# Frontend (Next.js)

> 모든 명령어는 **프로젝트 루트**에서 실행합니다.

## 요구사항

- Node.js 18.17 이상 (권장: 20 LTS)
- pnpm 9.12.3

## 시작하기

### 1. pnpm 활성화

```bash
corepack enable
corepack prepare pnpm@9.12.3 --activate
```

### 2. 의존성 설치

```bash
pnpm install
```

### 3. 환경변수 설정

```bash
cp apps/frontend/.env.example apps/frontend/.env
```

`.env`를 열어 필요한 값을 채워주세요.

### 4. 로컬 실행

```bash
pnpm --filter @las/frontend dev
```

접속: `http://localhost:3000`

## 자주 쓰는 명령어

```bash
pnpm --filter @las/frontend build      # 빌드
pnpm --filter @las/frontend lint       # 린트
pnpm --filter @las/frontend typecheck  # 타입 체크
```

## 캐시 초기화

화면/스타일이 이상할 때:

```bash
pkill -f "next dev|turbo" || true
rm -rf apps/frontend/.next
pnpm install --no-frozen-lockfile
pnpm --filter @las/frontend dev
```
