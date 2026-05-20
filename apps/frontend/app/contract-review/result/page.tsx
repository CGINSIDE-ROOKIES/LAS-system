"use client";

import { Suspense } from "react";
import ContractReviewResultPage from "@/screens/ContractReviewResult";

export default function Page() {
  return (
    <Suspense fallback={
      <div className="flex h-screen w-full items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-2">
          <span className="text-sm font-semibold text-muted-foreground">로딩 중...</span>
        </div>
      </div>
    }>
      <ContractReviewResultPage />
    </Suspense>
  );
}
