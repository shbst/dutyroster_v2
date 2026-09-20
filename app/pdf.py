import calendar
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

def make_pdf(data):
    pdfmetrics.registerFont(UnicodeCIDFont('HeiseiKakuGo-W5'))
    output=BytesIO(); width,height=landscape(A4)
    doc=SimpleDocTemplate(output,pagesize=(width,height),rightMargin=28,leftMargin=28,topMargin=24,bottomMargin=28,title='当直表',author='当直ノート')
    base=ParagraphStyle('base',fontName='HeiseiKakuGo-W5',fontSize=9,leading=13,wordWrap='CJK',textColor=colors.HexColor('#26364c'))
    title=ParagraphStyle('title',parent=base,fontSize=19,leading=25)
    small=ParagraphStyle('small',parent=base,fontSize=8,leading=11)
    names={m['id']:m['name'] for m in data['members']}; story=[]
    for index,month in enumerate(data['months']):
        if index: story.append(PageBreak())
        y,m=map(int,month.split('-'))
        story.append(Paragraph(f'{y}年 {m}月　当直表',title))
        story.append(Paragraph(f"{escape(data['name'])}　｜　{'確定' if data['status']=='final' else '下書き'}　｜　対象期間 {data['start']} - {data['end']}",small)); story.append(Spacer(1,10))
        rows=[[Paragraph(c,base) for c in '日月火水木金土']]
        style=[('BACKGROUND',(0,0),(-1,0),colors.HexColor('#eaf0fb')),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#d5deec')),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]
        for ri,week in enumerate(calendar.Calendar(firstweekday=6).monthdatescalendar(y,m),1):
            row=[]
            for ci,d in enumerate(week):
                ds=d.isoformat()
                if d.month!=m or ds not in data['days']:
                    row.append(''); continue
                info=data['days'][ds]
                lines=[f'<b>{d.day}</b> <font size="7">{escape(info["name"])}</font>']
                for kind,label in [('day','日直'),('night','当直')]:
                    slots=[s for s in data['slots'] if s['date']==ds and s['kind']==kind and s['enabled']]
                    if slots:
                        people=' / '.join(escape(names.get(s.get('member_id'),'未割当')) for s in slots)
                        lines.append(f'{label}　{people}')
                row.append(Paragraph('<br/>'.join(lines),small))
                if info['holiday']: style.append(('BACKGROUND',(ci,ri),(ci,ri),colors.HexColor('#f3f0fc')))
            rows.append(row)
        table=Table(rows,colWidths=[(width-56)/7]*7); table.setStyle(TableStyle(style)); story.append(table); story.append(Spacer(1,12))
        rows=[['メンバー','平日当直','休日日直','休日当直','合計','最短間隔']]
        for r in data['summaries'][month]:
            rows.append([Paragraph(escape(r['name']),base),r['weekday_night'],r['holiday_day'],r['holiday_night'],r['total'],f"{r['min_gap']}日" if r['min_gap'] is not None else '-'])
        totals=Table(rows,colWidths=[(width-56)*.3]+[(width-56)*.14]*5,repeatRows=1)
        totals.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),'HeiseiKakuGo-W5'),('FONTSIZE',(0,0),(-1,-1),9),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e6f4f1')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f8fafc')]),('ALIGN',(1,0),(-1,-1),'CENTER'),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3)])); story.append(totals)
    def footer(c,doc):
        c.setFont('HeiseiKakuGo-W5',8); c.setFillColor(colors.HexColor('#738095')); c.drawString(28,15,'当直ノート'); c.drawRightString(width-28,15,str(doc.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
