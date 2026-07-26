package com.agentrecruit.candidate;

import com.agentrecruit.ai.AiClient;
import com.agentrecruit.common.ApiException;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.stereotype.Component;

import java.util.Set;

/**
 * 简历文本提取：PDF 走本地 PDFBox；PNG/JPG 图片没有文本层，转发给 Python
 * AI 服务做 OCR 识别（见 AiClient#ocrResume）。
 */
@Component
public class ResumeParser {

    private static final Set<String> IMAGE_EXT = Set.of(".png", ".jpg", ".jpeg");

    private final AiClient aiClient;

    public ResumeParser(AiClient aiClient) {
        this.aiClient = aiClient;
    }

    public record PdfResult(String text, int pages) {
    }

    public PdfResult extractPdf(byte[] bytes) {
        try (PDDocument doc = Loader.loadPDF(bytes)) {
            String text = new PDFTextStripper().getText(doc).strip();
            return new PdfResult(text, doc.getNumberOfPages());
        } catch (Exception e) {
            throw new ApiException(422, "PDF 解析失败：" + e.getMessage());
        }
    }

    /** 按扩展名提取纯文本：.pdf 用 PDFBox 本地抽取；图片格式走 OCR 识别；其余返回空字符串。 */
    public String extractText(byte[] bytes, String ext) {
        if (".pdf".equals(ext)) {
            return extractPdf(bytes).text();
        }
        if (IMAGE_EXT.contains(ext)) {
            return aiClient.ocrResume(bytes, ext).orElse("");
        }
        return "";
    }
}
