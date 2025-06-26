import os
from io import BytesIO
from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

def export_to_excel(data, headers, filename):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    
    # Write headers
    ws.append(headers)
    
    # Write data
    for row in data:
        ws.append(row)
    
    # Save to BytesIO
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    return output, filename

def export_to_pdf(data, headers, title, filename):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    
    # Create elements
    elements = []
    styles = getSampleStyleSheet()
    
    # Add title
    elements.append(Paragraph(title, styles['Title']))
    elements.append(Paragraph(" ", styles['Normal']))  # Spacer
    
    # Create table data
    table_data = [headers]
    
    # Add data rows
    for row in data:
        table_row = []
        for item in row:
            # Create paragraphs for long text to enable wrapping
            if isinstance(item, str) and len(item) > 50:
                table_row.append(Paragraph(item, styles['Normal']))
            else:
                table_row.append(item)
        table_data.append(table_row)
    
    # Create table
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1a73e8")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor("#f8f9fa")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
    ]))
    
    elements.append(table)
    
    # Build PDF
    doc.build(elements)
    output.seek(0)
    
    return output, filename