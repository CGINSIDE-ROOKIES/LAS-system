# Frontend (Next.js)

## Frontend Local Setup

### 1) 설치해야 하는 것들

- `Node.js` 18.17 이상 (권장: 20 LTS)
- `corepack` (Node.js에 포함)
- `pnpm` 9.12.3 (`packageManager` 버전과 동일)

### 2) 환경변수 설정

```bash
cp apps/frontend/.env.example apps/frontend/.env
```

이후 `.env`를 열어 필요한 값을 채워주세요.

### 4) 의존성 설치

```bash
cd /home/user/projects/LAS-system
corepack enable
corepack prepare pnpm@9.12.3 --activate
pnpm install
```

### 5) 프론트엔드 로컬 실행

```bash
cd /home/user/projects/LAS-system
pnpm --filter @las/frontend dev
```

- 접속 주소: `http://localhost:3000`

### 6) 화면/스타일이 이상할 때 (캐시 초기화)

```bash
cd /home/user/projects/LAS-system
pkill -f "next dev|turbo" || true
rm -rf apps/frontend/.next
pnpm install --no-frozen-lockfile
pnpm --filter @las/frontend dev
```

### 7) 자주 쓰는 명령어

```bash
pnpm --filter @las/frontend build
pnpm --filter @las/frontend start
pnpm --filter @las/frontend lint
pnpm --filter @las/frontend typecheck
```
