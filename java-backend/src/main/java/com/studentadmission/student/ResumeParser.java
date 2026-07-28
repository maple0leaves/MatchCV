package com.studentadmission.student;

import com.studentadmission.ai.AiClient;
import com.studentadmission.common.ApiException;
import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.springframework.stereotype.Component;

import java.util.Set;





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
