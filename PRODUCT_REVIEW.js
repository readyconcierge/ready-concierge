const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageNumber, PageBreak, LevelFormat, TabStopType, TabStopPosition,
} = require("docx");

// ─── Color palette ───────────────────────────────────────────────
const NAVY    = "0A1628";
const GOLD    = "C8A96E";
const WHITE   = "FFFFFF";
const CREAM   = "F9F7F2";
const GRAY    = "666666";
const LTGRAY  = "999999";
const GREEN   = "2D6A2D";
const RED     = "8B1A1A";
const BORDER  = "D4CFC5";

// ─── Helper builders ─────────────────────────────────────────────
function spacer(pts = 120) {
  return new Paragraph({ spacing: { before: pts, after: pts }, children: [] });
}
function divider() {
  return new Paragraph({
    spacing: { before: 200, after: 200 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: GOLD, space: 1 } },
    children: [],
  });
}
function label(text) {
  return new Paragraph({
    spacing: { before: 60, after: 20 },
    children: [new TextRun({ text, font: "Arial", size: 16, color: GOLD, bold: true, allCaps: true, characterSpacing: 80 })],
  });
}
function bodyPara(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 160, line: 312 },
    children: [new TextRun({ text, font: "Georgia", size: 22, color: opts.color || "1A1A1A", bold: !!opts.bold, italics: !!opts.italics })],
  });
}
function bodyParaMulti(runs) {
  return new Paragraph({
    spacing: { after: 160, line: 312 },
    children: runs.map(r => new TextRun({ font: "Georgia", size: 22, color: "1A1A1A", ...r })),
  });
}
function heading2(text) {
  return new Paragraph({
    spacing: { before: 360, after: 160 },
    children: [new TextRun({ text, font: "Arial", size: 28, bold: true, color: NAVY })],
  });
}
function heading3(text) {
  return new Paragraph({
    spacing: { before: 280, after: 120 },
    children: [new TextRun({ text, font: "Arial", size: 24, bold: true, color: NAVY })],
  });
}
function callout(text, fillColor = "FFF8ED") {
  const border = { style: BorderStyle.SINGLE, size: 1, color: GOLD };
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({
      children: [new TableCell({
        borders: { top: border, bottom: border, right: border, left: { style: BorderStyle.SINGLE, size: 12, color: GOLD } },
        width: { size: 9360, type: WidthType.DXA },
        shading: { fill: fillColor, type: ShadingType.CLEAR },
        margins: { top: 160, bottom: 160, left: 240, right: 240 },
        children: [new Paragraph({
          spacing: { after: 0, line: 312 },
          children: [new TextRun({ text, font: "Georgia", size: 22, color: "1A1A1A", italics: true })],
        })],
      })]
    })],
  });
}
function verdict(grade, text) {
  const color = grade === "A" ? GREEN : grade === "B" ? "7A5C00" : RED;
  return new Paragraph({
    spacing: { before: 80, after: 200 },
    children: [
      new TextRun({ text: `VERDICT: ${grade} `, font: "Arial", size: 22, bold: true, color }),
      new TextRun({ text: `\u2014 ${text}`, font: "Georgia", size: 22, color: GRAY, italics: true }),
    ],
  });
}

// ─── Numbering config ────────────────────────────────────────────
const numberingConfig = [
  {
    reference: "recs",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
  {
    reference: "recs2",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
  {
    reference: "recs3",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
  {
    reference: "recs4",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
  {
    reference: "recs5",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
  {
    reference: "recs6",
    levels: [{
      level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 720, hanging: 360 } }, run: { font: "Arial", bold: true, size: 22, color: NAVY } },
    }],
  },
];

function recItem(ref, text) {
  return new Paragraph({
    numbering: { reference: ref, level: 0 },
    spacing: { after: 120, line: 312 },
    children: [new TextRun({ text, font: "Georgia", size: 22, color: "1A1A1A", bold: false })],
  });
}

// ═══════════════════════════════════════════════════════════════════
// DOCUMENT
// ═══════════════════════════════════════════════════════════════════

const doc = new Document({
  numbering: { config: numberingConfig },
  styles: {
    default: { document: { run: { font: "Georgia", size: 22 } } },
  },
  sections: [
    // ── COVER PAGE ──────────────────────────────────────────────────
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      children: [
        spacer(2400),
        label("PRODUCT REVIEW"),
        new Paragraph({
          spacing: { before: 120, after: 40 },
          children: [new TextRun({ text: "Ready Concierge", font: "Georgia", size: 56, bold: true, color: NAVY })],
        }),
        new Paragraph({
          spacing: { after: 200 },
          children: [new TextRun({ text: "Making it inevitable.", font: "Georgia", size: 28, color: GOLD, italics: true })],
        }),
        divider(),
        spacer(120),
        bodyPara("A first-principles product review of Ready Concierge \u2014 what it is, what it gets right, what\u2019s holding it back, and the specific changes that will make it something people can\u2019t shut up about.", { color: GRAY }),
        spacer(600),
        new Paragraph({
          spacing: { after: 40 },
          children: [new TextRun({ text: "Prepared for Nate Brown", font: "Arial", size: 20, color: LTGRAY })],
        }),
        new Paragraph({
          spacing: { after: 40 },
          children: [new TextRun({ text: "April 2026", font: "Arial", size: 20, color: LTGRAY })],
        }),
        new Paragraph({
          children: [new TextRun({ text: "Preshift", font: "Arial", size: 20, color: LTGRAY })],
        }),
      ],
    },

    // ── MAIN CONTENT ────────────────────────────────────────────────
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, right: 1440, bottom: 1080, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [new Paragraph({
            spacing: { after: 0 },
            border: { bottom: { style: BorderStyle.SINGLE, size: 2, color: BORDER, space: 4 } },
            children: [
              new TextRun({ text: "READY CONCIERGE", font: "Arial", size: 14, color: LTGRAY, characterSpacing: 60 }),
              new TextRun({ text: "\tPRODUCT REVIEW", font: "Arial", size: 14, color: LTGRAY, characterSpacing: 60 }),
            ],
            tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
          })],
        }),
      },
      footers: {
        default: new Footer({
          children: [new Paragraph({
            alignment: AlignmentType.CENTER,
            children: [
              new TextRun({ text: "Page ", font: "Arial", size: 16, color: LTGRAY }),
              new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 16, color: LTGRAY }),
            ],
          })],
        }),
      },
      children: [

        // ── I. THE ONE-SENTENCE PITCH ───────────────────────────────
        heading2("I. The One-Sentence Pitch"),
        callout("Forward any email. Get a draft reply back in your inbox in under 30 seconds. That\u2019s it. That\u2019s the product."),
        spacer(40),
        bodyPara("This is the right instinct. The best products in history reduce a complex workflow to one action. Google reduced the entire internet to a search box. Uber reduced transportation to a button. Ready Concierge reduces \u201Ccrafting a thoughtful hotel reply\u201D to hitting Forward."),
        bodyPara("The forward-to-draft model is the single most important architectural decision in this product. It means zero onboarding for staff. Zero logins. Zero new apps. You use the email client you already have. That is powerful."),
        bodyPara("But right now, the product doesn\u2019t fully capitalize on this insight. Let me explain what I mean."),

        // ── II. WHAT YOU\u2019VE BUILT ────────────────────────────────────
        heading2("II. What You\u2019ve Actually Built"),
        bodyPara("I\u2019ve read every file. Let me be direct: the engineering here is considerably more advanced than most products at this stage. Here\u2019s the current architecture:"),
        spacer(40),
        heading3("The Core Loop (Working)"),
        bodyPara("Staff forwards an email to their stream\u2019s inbound address. SendGrid catches it, POSTs to /webhook/inbound. The parser detects forwarded content (Gmail, Outlook, Apple Mail formats), extracts the original sender/subject/body. Claude Haiku classifies intent across 10 categories. Claude Haiku generates a Five-Star draft reply. A guardrail system evaluates the draft for safety. If it passes, SendGrid delivers the draft back to the forwarder\u2019s inbox. If it fails, it\u2019s held for review. Tasks are automatically extracted from the draft. Everything is persisted to Postgres."),
        bodyPara("That\u2019s a serious pipeline. And it works."),
        spacer(40),
        heading3("The Signal Layer (Working)"),
        bodyPara("Once or twice daily, the system scans all emails in a time window, runs pattern detection (volume spikes, arrival clusters, celebration clusters, negative sentiment, multi-signal guests), feeds everything to Claude Sonnet, and emails a structured intelligence briefing to management. The briefing prompt is excellent \u2014 it enforces analyst-style writing, not AI-speak."),
        spacer(40),
        heading3("The Dashboard (Working)"),
        bodyPara("A Next.js dashboard on Vercel with five pages: Review Queue (approve/reject held drafts), Email History (full timeline with expandable draft previews), Task List (with checkbox completion and email-based \u201Cdone\u201D replies), Knowledge Base (upload documents for RAG context), and Settings (authorized senders, stream config). Property/Stream hierarchy in the sidebar. Clean design. Functional."),
        spacer(40),
        heading3("The Architecture (Ambitious)"),
        bodyPara("Company \u2192 Property \u2192 Stream. Multi-tenant from day one. Each stream gets its own inbox, knowledge base, task list, and signal schedule. The digest system lets staff email list@domain to get a task list, then reply \u201Cdone all\u201D to mark tasks complete without logging in."),
        bodyPara("This is not a prototype. This is a working product with real infrastructure behind it."),

        // ── III. THE HARD TRUTH ──────────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        heading2("III. The Hard Truth"),
        callout("The product does too many things adequately instead of one thing so well that people can\u2019t stop talking about it.", "FFF0F0"),
        spacer(40),
        bodyPara("Here\u2019s what Jobs would say: you\u2019ve built the signal layer, the task extraction system, the digest emails, the knowledge base, the review queue, the multi-tenant architecture, the guardrails, the dashboard. That\u2019s eight systems. Each one is competent. None of them are extraordinary."),
        bodyPara("The magic moment \u2014 the thing that makes someone\u2019s jaw drop \u2014 is the 30-second draft reply. That\u2019s the only thing that matters right now. Everything else is a distraction from making that moment perfect."),
        bodyParaMulti([
          { text: "Musk\u2019s principle: ", bold: true },
          { text: "the best part is no part. Every feature you ship that isn\u2019t the core experience is weight you\u2019re carrying. The signal layer is cool. The task extraction is clever. But if the draft reply isn\u2019t so good that a concierge reads it and whispers \u201Choly shit\u201D under their breath, none of that matters." },
        ]),

        // ── IV. WHAT MAKES A PRODUCT INEVITABLE ──────────────────────
        heading2("IV. What Makes a Product Inevitable"),
        bodyPara("Three conditions must be true:"),
        spacer(20),
        heading3("1. The first experience must be a revelation"),
        bodyPara("The very first draft reply a concierge receives must be better than what they would have written themselves. Not comparable. Better. If they read it and think \u201CI could have written that,\u201D you\u2019ve lost. If they read it and think \u201CThis noticed something about the guest that I missed,\u201D you\u2019ve won."),
        bodyPara("Your draft prompt already has the right instinct with the Forbes Five-Star standards and the anticipatory service guidance (\u201Cread what the guest reveals about themselves\u201D). But the current Haiku model may not be sophisticated enough to consistently deliver that level of emotional intelligence. This is the one place where the model quality tradeoff might be wrong."),
        verdict("B+", "The prompt is excellent. The model choice is the bottleneck."),
        spacer(40),

        heading3("2. The workflow must be frictionless to the point of invisibility"),
        bodyPara("Forward-to-draft is nearly perfect. But there are friction points. The draft arrives as an email the concierge has to read, mentally parse the header, find the actual draft text, copy it, open a new reply to the guest, paste it, review, and send. That\u2019s six steps after the draft arrives."),
        bodyPara("The killer version: the draft is pre-formatted as a reply-ready message where one click opens a pre-composed email to the guest. Or better: staff hits Forward, and the system sends the reply directly with a 5-minute delay window where they can cancel or edit via a single link. The point is to make the distance between \u201CI forwarded it\u201D and \u201Cthe guest got a reply\u201D as short as physically possible."),
        verdict("A-", "Forward-to-reply is the right model. Reduce the steps after the draft lands."),
        spacer(40),

        heading3("3. The product must create visible social proof"),
        bodyPara("When a concierge uses Ready Concierge and a guest replies with \u201CWow, that was the fastest and most thoughtful response I\u2019ve ever gotten from a hotel,\u201D the concierge tells their colleagues. That\u2019s how this spreads inside a property. And when the GM sees reply times drop from 45 minutes to 3 minutes, they tell other GMs. That\u2019s how this spreads across properties."),
        bodyPara("Right now there\u2019s no mechanism to capture this. No reply-time tracking. No guest satisfaction signal. No \u201Cthis draft was used as-is\u201D metric. The product generates enormous value but has no way to show it to anyone."),
        verdict("C", "The value is invisible. You need a feedback loop."),

        // ── V. THE RECOMMENDATIONS ───────────────────────────────────
        new Paragraph({ children: [new PageBreak()] }),
        heading2("V. Recommendations"),
        bodyPara("In priority order. Do these in sequence, not in parallel."),
        spacer(40),

        // --- Rec 1 ---
        heading3("Make the Draft Reply Extraordinary"),
        label("PRIORITY: EXISTENTIAL"),
        bodyPara("This is the product. Everything flows from here."),
        recItem("recs", "Test Sonnet for draft generation on the hardest 20% of emails (complaints, VIP multi-request, emotionally complex situations). If the quality jump justifies the cost, use Sonnet for those categories and Haiku for everything else. The guardrail system already classifies by intent \u2014 use it as a model router."),
        recItem("recs", "Add a \u201Cguest memory\u201D layer. When the same guest emails twice, the second draft should reference the first interaction. \u201CWe\u2019re glad to hear from you again, Sarah \u2014 we hope the anniversary dinner was everything you hoped for.\u201D This is the single most impressive thing a draft can do, and no competitor can match it at the speed you operate."),
        recItem("recs", "The draft prompt\u2019s closing question (\u201CWhat\u2019s the most important part of your stay?\u201D) is brilliant. But it should be the first thing a new guest hears, not a recurring closer. After the first email, the system should already know the answer and use it. That\u2019s what makes anticipatory service feel real."),
        recItem("recs", "Load the knowledge base by default with the 20 things every luxury hotel guest asks about: pool hours, checkout time, parking, restaurant hours, room service, wifi, pet policy, spa hours, fitness center, nearby attractions. Don\u2019t wait for the hotel to upload docs. Provide a starter template they can customize in 10 minutes."),
        spacer(40),

        // --- Rec 2 ---
        heading3("Collapse the Distance Between Draft and Send"),
        label("PRIORITY: CRITICAL"),
        bodyPara("Every second between \u201Cdraft received\u201D and \u201Cguest gets a reply\u201D is friction that kills the magic."),
        recItem("recs2", "Add a \u201CSend to Guest\u201D button directly in the draft email. When clicked, it opens a mailto: link pre-populated with the guest\u2019s address, the subject line, and the draft text in the body. One click to review, one click to send. Two steps total."),
        recItem("recs2", "For the highest-confidence drafts (guardrail = high, no sensitive flags, knowledge-backed), offer an auto-send mode with a 5-minute cancellation window. The email says: \u201CThis reply will be sent in 5 minutes. Click here to edit or cancel.\u201D This turns the workflow from opt-in to opt-out \u2014 which is what separates tools from copilots."),
        recItem("recs2", "Track and display average reply time: \u201CReady Concierge helped your team reply in an average of 2 minutes and 14 seconds today.\u201D Put this in the daily signal. That number is the ROI story."),
        spacer(40),

        // --- Rec 3 ---
        heading3("Build the Feedback Loop"),
        label("PRIORITY: HIGH"),
        bodyPara("Without a feedback loop, you\u2019re flying blind and the product can\u2019t improve itself."),
        recItem("recs3", "Track draft usage: did the staff member send a reply within 10 minutes of receiving the draft? If yes, it was probably used. That\u2019s your \u201Cacceptance rate\u201D proxy without requiring any extra action from staff."),
        recItem("recs3", "In the draft email, add two links at the bottom: \u201CThis draft was perfect\u201D and \u201CThis draft needed changes.\u201D One click, no login, writes directly to the DraftReply.accepted column that\u2019s already in your schema. This is the minimum viable feedback mechanism."),
        recItem("recs3", "Build a weekly digest that goes to the GM: emails handled, average reply time, acceptance rate, guest satisfaction signals. This is the \u201Cproof it\u2019s working\u201D email. It\u2019s also the sales tool for the next property."),
        spacer(40),

        // --- Rec 4 ---
        heading3("Simplify Onboarding to Under 10 Minutes"),
        label("PRIORITY: HIGH"),
        bodyPara("The current setup requires API keys, SendGrid configuration, DNS verification, and Railway deployment. That\u2019s a developer task. If you want hotel staff to tell their friends about this, you need a non-technical setup path."),
        recItem("recs4", "Build a one-page onboarding wizard: enter hotel name, staff email addresses, and paste your concierge inbox info. The system provisions the stream, generates the forwarding address, and sends a test email within 60 seconds. No API keys visible. No deployment steps."),
        recItem("recs4", "The first thing a new user should see after setup is a test email arriving in their inbox with a draft reply to a sample guest request. The \u201Choly shit\u201D moment should happen in minute one, not after an hour of configuration."),
        recItem("recs4", "Pre-populate the knowledge base with a luxury hotel starter pack. Pool hours, dining info, checkout policy, spa services. The hotel edits what\u2019s different; they don\u2019t start from blank."),
        spacer(40),

        // --- Rec 5 ---
        heading3("Make the Signal Layer a Competitive Moat"),
        label("PRIORITY: MEDIUM"),
        bodyPara("The signal briefing is genuinely good. But it\u2019s a feature, not a habit. To make it a habit:"),
        recItem("recs5", "Send the signal at the exact time the morning team arrives (configurable per property \u2014 already supported). Add a 2-line SMS/text version for the GM. The full email is for the concierge desk; the text is for the person who needs to know in 10 seconds whether anything is on fire."),
        recItem("recs5", "Add a \u201Cweek-over-week\u201D comparison to the signal: \u201C23% more dining requests than last Tuesday. Likely due to the wine festival.\u201D Context turns data into intelligence. Intelligence creates dependency."),
        recItem("recs5", "Let the signal auto-generate prep lists: \u201C3 arrivals between 2\u20134 PM. All have requested airport transfers. Vehicles confirmed: 2 of 3.\u201D This turns a briefing into a todo list, which is more actionable than a summary."),
        spacer(40),

        // --- Rec 6 ---
        heading3("Defer Everything Else"),
        label("PRIORITY: DISCIPLINE"),
        bodyPara("The following features are in the codebase or implied by the architecture. Do not build them further until the core draft experience is extraordinary and you have 3+ properties live:"),
        recItem("recs6", "Multi-company tenancy. One company, one property, one stream. That\u2019s your pilot. Multi-tenant is an enterprise problem; solve it when you have enterprise customers."),
        recItem("recs6", "The dashboard beyond its current state. The dashboard is a nice-to-have. The product lives in email. If people have to log into a dashboard to get value, you\u2019ve already lost. The dashboard is for admins, not for daily users."),
        recItem("recs6", "PDF/file upload for knowledge base. Text paste is fine. You can extract PDF content later. Don\u2019t solve file parsing until someone actually asks for it."),
        recItem("recs6", "Hourly signals. Start with daily. Hourly is noise until you have enough email volume to justify it."),

        // ── VI. WHAT MAKES PEOPLE TELL THEIR FRIENDS ─────────────────
        new Paragraph({ children: [new PageBreak()] }),
        heading2("VI. What Makes People Tell Their Friends"),
        callout("People don\u2019t tell their friends about adequate software. They tell their friends about moments that surprised them."),
        spacer(40),
        bodyPara("Here are the moments that will spread this product:"),
        spacer(20),
        bodyParaMulti([
          { text: "The speed moment: ", bold: true },
          { text: "\u201CI forwarded an email at 9:47 and by 9:48 I had a better reply than I would have written in 20 minutes.\u201D" },
        ]),
        bodyParaMulti([
          { text: "The intelligence moment: ", bold: true },
          { text: "\u201CThe draft noticed the guest mentioned their daughter\u2019s birthday and offered to arrange a cake. I didn\u2019t even catch that.\u201D" },
        ]),
        bodyParaMulti([
          { text: "The memory moment: ", bold: true },
          { text: "\u201CA repeat guest emailed and the draft referenced their last stay. The guest thought we had a photographic memory.\u201D" },
        ]),
        bodyParaMulti([
          { text: "The coverage moment: ", bold: true },
          { text: "\u201CI went on vacation for a week. My team used Ready Concierge and not a single guest noticed I was gone.\u201D" },
        ]),
        bodyParaMulti([
          { text: "The proof moment: ", bold: true },
          { text: "\u201CThe GM got a report showing we replied to every email in under 5 minutes for the entire month. He showed it to the regional VP.\u201D" },
        ]),
        spacer(40),
        bodyPara("Every recommendation above is designed to create one of these moments. The speed moment comes from collapsing the send workflow. The intelligence moment comes from better models and anticipatory prompting. The memory moment comes from guest history. The coverage moment comes from reliability and auto-send. The proof moment comes from the feedback loop and the weekly digest."),

        // ── VII. CLOSING ──────────────────────────────────────────────
        heading2("VII. The Bottom Line"),
        divider(),
        bodyPara("Ready Concierge is not a prototype. It\u2019s a real product with real architecture, real infrastructure, and a real insight at its core: the best AI tool for email is one that lives inside email."),
        bodyPara("The risk is not technical. The risk is diffusion \u2014 building outward instead of deeper. The signal layer, the task system, the multi-tenant architecture, the dashboard: these are all good ideas that are pulling focus from the one thing that needs to be undeniably great."),
        bodyParaMulti([
          { text: "Make the draft reply so good that a concierge shows their phone to the person standing next to them and says: \u201Clook at this.\u201D", bold: true },
          { text: " That\u2019s the bar. Everything else is a consequence of clearing it." },
        ]),
        spacer(80),
        divider(),
        spacer(40),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 40 },
          children: [new TextRun({ text: "Ready Concierge Product Review", font: "Arial", size: 18, color: LTGRAY })],
        }),
        new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ text: "April 2026 \u00B7 Preshift", font: "Arial", size: 18, color: LTGRAY })],
        }),
      ],
    },
  ],
});

// ─── Generate ────────────────────────────────────────────────────
Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/sessions/intelligent-trusting-ramanujan/mnt/ready-concierge/Ready_Concierge_Product_Review.docx", buffer);
  console.log("Done.");
});
