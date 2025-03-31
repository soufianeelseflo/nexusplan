# backend/app/services/report_service.py
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Frame, PageTemplate, BaseDocTemplate, NextPageTemplate, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import navy, black, gray, white
from reportlab.lib.pagesizes import A4
from app.core.config import settings # For project name etc.
import os
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

# --- Custom Styles ---
def get_custom_styles() -> Dict[str, ParagraphStyle]:
    """Defines custom paragraph styles for the report."""
    styles = getSampleStyleSheet()
    custom_styles = {
        'TitleStyle': ParagraphStyle(
            name='TitleStyle',
            parent=styles['h1'],
            fontSize=24,
            alignment=TA_CENTER,
            spaceAfter=0.5*inch,
            textColor=navy
        ),
        'SubTitleStyle': ParagraphStyle(
            name='SubTitleStyle',
            parent=styles['h3'],
            fontSize=14,
            alignment=TA_CENTER,
            spaceAfter=0.1*inch,
            textColor=gray
        ),
        'Heading1Style': ParagraphStyle(
            name='Heading1Style',
            parent=styles['h1'],
            fontSize=18,
            spaceBefore=18,
            spaceAfter=12,
            textColor=navy,
            alignment=TA_LEFT
        ),
        'Heading2Style': ParagraphStyle(
            name='Heading2Style',
            parent=styles['h2'],
            fontSize=14,
            spaceBefore=12,
            spaceAfter=8,
            textColor=navy,
            alignment=TA_LEFT
        ),
        'NormalStyle': ParagraphStyle(
            name='NormalStyle',
            parent=styles['Normal'],
            fontSize=11,
            alignment=TA_JUSTIFY,
            spaceAfter=6,
            leading=14 # Line spacing
        ),
        'FooterStyle': ParagraphStyle(
            name='FooterStyle',
            parent=styles['Normal'],
            fontSize=8,
            alignment=TA_CENTER,
            textColor=gray
        ),
    }
    return custom_styles

# --- Header/Footer Logic ---
def header(canvas, doc, content: str):
    """Draws header content on each page."""
    canvas.saveState()
    styles = get_custom_styles()
    header_text = Paragraph(content, styles['FooterStyle']) # Use footer style for header text size
    w, h = header_text.wrap(doc.width, doc.topMargin)
    header_text.drawOn(canvas, doc.leftMargin, doc.height + doc.topMargin - h - 0.1*inch) # Position header
    # Draw a line below header
    canvas.setStrokeColor(gray)
    canvas.line(doc.leftMargin, doc.height + doc.topMargin - h - 0.15*inch,
                doc.leftMargin + doc.width, doc.height + doc.topMargin - h - 0.15*inch)
    canvas.restoreState()

def footer(canvas, doc, content: str):
    """Draws footer content on each page."""
    canvas.saveState()
    styles = get_custom_styles()
    footer_text = Paragraph(content, styles['FooterStyle'])
    w, h = footer_text.wrap(doc.width, doc.bottomMargin)
    footer_text.drawOn(canvas, doc.leftMargin, doc.bottomMargin - h + 0.1*inch) # Position footer
    # Add page number
    page_num_text = f"Page {doc.page}"
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(gray)
    canvas.drawRightString(doc.leftMargin + doc.width, doc.bottomMargin - h + 0.1*inch, page_num_text)
    canvas.restoreState()

# --- Main PDF Generation Function ---
async def generate_pdf_report(report_data: Dict[str, Any], filename_base: str) -> str:
    """
    Generates a professional-looking PDF report using ReportLab.
    Takes report data dictionary and a base filename.
    Returns the full path to the generated PDF file.
    """
    # Define file path (use /tmp in containerized environments)
    pdf_directory = "/tmp"
    if not os.path.exists(pdf_directory):
        os.makedirs(pdf_directory, exist_ok=True) # Ensure directory exists
    pdf_filepath = os.path.join(pdf_directory, f"{filename_base}.pdf")

    logger.info(f"Starting PDF generation for: {pdf_filepath}")

    try:
        # --- Document Setup ---
        doc = BaseDocTemplate(pdf_filepath, pagesize=A4,
                              leftMargin=1*inch, rightMargin=1*inch,
                              topMargin=1*inch, bottomMargin=1*inch)

        # Define frames for content area
        frame_main = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                           id='main_frame', leftPadding=0, bottomPadding=0,
                           rightPadding=0, topPadding=0)

        # --- Define Page Templates ---
        styles = get_custom_styles()
        report_title = report_data.get("title", "Intelligence Report")
        footer_content = f"© {datetime.now().year} {settings.PROJECT_NAME} | Confidential"

        # Define header/footer functions with specific content
        header_func = lambda canvas, doc: header(canvas, doc, report_title)
        footer_func = lambda canvas, doc: footer(canvas, doc, footer_content)

        # Create page templates
        main_page_template = PageTemplate(id='main_page', frames=[frame_main],
                                          onPage=header_func, onPageEnd=footer_func)

        doc.addPageTemplates([main_page_template])

        # --- Build Story (Content Flowables) ---
        story = []
        client_name = report_data.get("client_name", "Valued Client")
        report_date = datetime.now().strftime("%B %d, %Y")
        executive_summary = report_data.get("executive_summary", "No summary provided.")
        sections = report_data.get("sections", []) # List of dicts {"title": "...", "content": "..."}

        # Title Page Elements (Add to story first)
        story.append(Paragraph(report_title, styles['TitleStyle']))
        story.append(Spacer(1, 0.2*inch))
        story.append(Paragraph(f"Prepared for: {client_name}", styles['SubTitleStyle']))
        story.append(Paragraph(f"Date: {report_date}", styles['SubTitleStyle']))
        story.append(PageBreak()) # Move to next page for content

        # Main Content
        story.append(NextPageTemplate('main_page')) # Ensure subsequent pages use the main template

        # Executive Summary
        story.append(Paragraph("Executive Summary", styles['Heading1Style']))
        story.append(Paragraph(executive_summary.replace('\n', '<br/>'), styles['NormalStyle']))
        story.append(Spacer(1, 0.2*inch))

        # Report Sections
        for section in sections:
            section_title = section.get("title", "Untitled Section")
            section_content = section.get("content", "No content provided.")
            if section_title and section_content and section_content != "N/A": # Only add sections with content
                story.append(Paragraph(section_title, styles['Heading2Style']))
                # Replace newlines for ReportLab paragraphs
                formatted_content = section_content.replace('\n', '<br/>')
                story.append(Paragraph(formatted_content, styles['NormalStyle']))
                story.append(Spacer(1, 0.1*inch))

        # --- Build the PDF Document ---
        logger.info("Building PDF document...")
        doc.build(story)
        logger.info(f"PDF report generated successfully: {pdf_filepath}")
        return pdf_filepath

    except Exception as e:
        logger.error(f"Failed to generate PDF report '{pdf_filepath}': {e}", exc_info=True)
        # Re-raise the exception so the calling function knows generation failed
        raise RuntimeError(f"PDF Generation Failed: {e}")