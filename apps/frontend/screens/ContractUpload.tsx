import { useState, useCallback } from "react";
import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/AppSidebar";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "sonner";
import {
  Upload,
  FileText,
  X,
  CheckCircle2,
  AlertCircle,
  FileSearch,
  MessageSquare,
  FilePen,
  Loader2,
} from "lucide-react";
import { cn } from "@/lib/utils";

type UploadStatus = "idle" | "uploading" | "success" | "error" | "processing";

interface UploadedFile {
  name: string;
  size: number;
  type: string;
}

const SUPPORTED_FORMATS = [".hwp", ".hwpx", ".doc", ".docx", ".pdf"];
const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return "0 Bytes";
  const k = 1024;
  const sizes = ["Bytes", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
};

const getFileExtension = (filename: string): string => {
  return filename.slice(filename.lastIndexOf(".")).toLowerCase();
};

const ContractUpload = () => {
  const [isDragging, setIsDragging] = useState(false);
  const [uploadedFile, setUploadedFile] = useState<UploadedFile | null>(null);
  const [uploadStatus, setUploadStatus] = useState<UploadStatus>("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [contractType, setContractType] = useState<string>("");

  const validateFile = (file: File): string | null => {
    const extension = getFileExtension(file.name);
    if (!SUPPORTED_FORMATS.includes(extension)) {
      return `지원하지 않는 파일 형식입니다. (${SUPPORTED_FORMATS.join(", ")})`;
    }
    if (file.size > MAX_FILE_SIZE) {
      return `파일 크기가 50MB를 초과합니다.`;
    }
    return null;
  };

  const simulateUpload = useCallback((file: File) => {
    setUploadStatus("uploading");
    setUploadProgress(0);

    const interval = setInterval(() => {
      setUploadProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setUploadStatus("processing");
          
          // Simulate processing
          setTimeout(() => {
            setUploadStatus("success");
            toast.success("파일이 성공적으로 업로드되었습니다.");
          }, 1500);
          
          return 100;
        }
        return prev + Math.random() * 15 + 5;
      });
    }, 200);
  }, []);

  const handleFile = useCallback((file: File) => {
    const error = validateFile(file);
    if (error) {
      toast.error(error);
      setUploadStatus("error");
      return;
    }

    setUploadedFile({
      name: file.name,
      size: file.size,
      type: getFileExtension(file.name).replace(".", "").toUpperCase(),
    });

    simulateUpload(file);
  }, [simulateUpload]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const files = e.dataTransfer.files;
    if (files.length > 0) {
      handleFile(files[0]);
    }
  }, [handleFile]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (files && files.length > 0) {
      handleFile(files[0]);
    }
  }, [handleFile]);

  const handleRemoveFile = () => {
    setUploadedFile(null);
    setUploadStatus("idle");
    setUploadProgress(0);
  };

  const handleStartReview = () => {
    if (!uploadedFile) {
      toast.error("먼저 계약서를 업로드해주세요.");
      return;
    }
    if (!contractType) {
      toast.error("계약서 유형을 선택해주세요.");
      return;
    }
    toast.info("법률 검토를 시작합니다.", {
      description: `${uploadedFile.name} 파일을 분석 중입니다.`,
    });
  };

  const handleAskQuestions = () => {
    if (!uploadedFile) {
      toast.error("먼저 계약서를 업로드해주세요.");
      return;
    }
    toast.info("질문 모드로 전환합니다.", {
      description: "업로드된 계약서에 대해 질문할 수 있습니다.",
    });
  };

  const handleGenerateDraft = () => {
    toast.info("초안 생성 기능", {
      description: "템플릿 기반 계약서 초안을 생성합니다.",
    });
  };

  return (
    <SidebarProvider>
      <div className="flex min-h-screen w-full">
        <AppSidebar />
        <div className="flex flex-1 flex-col">
          <header className="flex h-10 items-center border-b border-border px-2">
            <SidebarTrigger />
          </header>

          <div className="flex-1 overflow-auto bg-muted/30 p-6">
            <div className="mx-auto max-w-3xl space-y-6">
              {/* Header */}
              <div>
                <h1 className="text-2xl font-semibold text-foreground">계약서 검토</h1>
                <p className="text-sm text-muted-foreground">
                  계약서를 업로드하여 AI 기반 법률 검토를 받거나 질문할 수 있습니다.
                </p>
              </div>

              {/* Upload Area */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">계약서 업로드</CardTitle>
                  <CardDescription>
                    검토할 계약서 파일을 업로드하세요.
                  </CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  {/* Drag & Drop Zone */}
                  {!uploadedFile ? (
                    <div
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                      className={cn(
                        "relative flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors",
                        isDragging
                          ? "border-primary bg-primary/5"
                          : "border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/50"
                      )}
                    >
                      <Upload
                        className={cn(
                          "mb-4 h-12 w-12",
                          isDragging ? "text-primary" : "text-muted-foreground"
                        )}
                      />
                      <p className="mb-2 text-sm font-medium text-foreground">
                        파일을 드래그하여 업로드하거나
                      </p>
                      <label htmlFor="file-upload">
                        <Button variant="outline" size="sm" asChild>
                          <span className="cursor-pointer">파일 선택</span>
                        </Button>
                        <input
                          id="file-upload"
                          type="file"
                          className="hidden"
                          accept={SUPPORTED_FORMATS.join(",")}
                          onChange={handleFileSelect}
                        />
                      </label>
                      <div className="mt-4 space-y-1 text-center">
                        <p className="text-xs text-muted-foreground">
                          지원 형식: HWP, HWPX, DOC, DOCX, PDF
                        </p>
                        <p className="text-xs text-muted-foreground">
                          최대 파일 크기: 50MB
                        </p>
                      </div>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      {/* Uploaded File Info */}
                      <div className="flex items-center gap-4 rounded-lg border border-border bg-muted/30 p-4">
                        <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10">
                          <FileText className="h-6 w-6 text-primary" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="truncate font-medium text-foreground">
                            {uploadedFile.name}
                          </p>
                          <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Badge variant="secondary" className="text-xs">
                              {uploadedFile.type}
                            </Badge>
                            <span>{formatFileSize(uploadedFile.size)}</span>
                          </div>
                        </div>
                        {uploadStatus === "success" && (
                          <CheckCircle2 className="h-5 w-5 text-primary" />
                        )}
                        {uploadStatus === "error" && (
                          <AlertCircle className="h-5 w-5 text-destructive" />
                        )}
                        {uploadStatus === "processing" && (
                          <Loader2 className="h-5 w-5 animate-spin text-primary" />
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={handleRemoveFile}
                          className="shrink-0"
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>

                      {/* Upload Progress */}
                      {(uploadStatus === "uploading" || uploadStatus === "processing") && (
                        <div className="space-y-2">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-muted-foreground">
                              {uploadStatus === "uploading" ? "업로드 중..." : "파일 처리 중..."}
                            </span>
                            <span className="font-medium text-foreground">
                              {Math.min(Math.round(uploadProgress), 100)}%
                            </span>
                          </div>
                          <Progress value={Math.min(uploadProgress, 100)} className="h-2" />
                        </div>
                      )}

                      {/* Status Message */}
                      {uploadStatus === "success" && (
                        <div className="flex items-center gap-2 rounded-lg bg-accent/50 p-3 text-sm text-accent-foreground">
                          <CheckCircle2 className="h-4 w-4 text-primary" />
                          파일이 성공적으로 업로드되었습니다. 아래에서 작업을 선택하세요.
                        </div>
                      )}

                      {uploadStatus === "error" && (
                        <div className="flex items-center gap-2 rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
                          <AlertCircle className="h-4 w-4" />
                          파일 업로드에 실패했습니다. 다시 시도해주세요.
                        </div>
                      )}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Contract Type Selection */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">계약서 유형</CardTitle>
                  <CardDescription>
                    정확한 분석을 위해 계약서 유형을 선택하세요.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <Select value={contractType} onValueChange={setContractType}>
                    <SelectTrigger className="w-full max-w-sm">
                      <SelectValue placeholder="계약서 유형 선택" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="employment">근로계약서 (Employment Contract)</SelectItem>
                      <SelectItem value="subcontract">하도급 계약서 (Subcontract Agreement)</SelectItem>
                      <SelectItem value="service">용역 계약서 (Service Agreement)</SelectItem>
                      <SelectItem value="nda">비밀유지계약서 (NDA)</SelectItem>
                      <SelectItem value="other">기타 (Other)</SelectItem>
                    </SelectContent>
                  </Select>
                </CardContent>
              </Card>

              {/* Action Buttons */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">작업 선택</CardTitle>
                  <CardDescription>
                    업로드된 계약서로 수행할 작업을 선택하세요.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <Button
                      onClick={handleStartReview}
                      disabled={uploadStatus !== "success"}
                      className="h-auto flex-col gap-2 py-6"
                    >
                      <FileSearch className="h-6 w-6" />
                      <div className="text-center">
                        <p className="font-medium">법률 검토 시작</p>
                        <p className="text-xs font-normal opacity-80">
                          계약서 조항 분석
                        </p>
                      </div>
                    </Button>

                    <Button
                      variant="outline"
                      onClick={handleAskQuestions}
                      disabled={uploadStatus !== "success"}
                      className="h-auto flex-col gap-2 py-6"
                    >
                      <MessageSquare className="h-6 w-6" />
                      <div className="text-center">
                        <p className="font-medium">질문하기</p>
                        <p className="text-xs font-normal text-muted-foreground">
                          계약서 관련 Q&A
                        </p>
                      </div>
                    </Button>

                    <Button
                      variant="outline"
                      onClick={handleGenerateDraft}
                      className="h-auto flex-col gap-2 py-6"
                    >
                      <FilePen className="h-6 w-6" />
                      <div className="text-center">
                        <p className="font-medium">초안 생성</p>
                        <p className="text-xs font-normal text-muted-foreground">
                          템플릿 기반 작성
                        </p>
                      </div>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>
      </div>
    </SidebarProvider>
  );
};

export default ContractUpload;
