# Corpus sources

Where the RAG corpus comes from. Each corpus document (written in S11) is a markdown file
summarising **one** page from this list, with `source_url` and `retrieved_on` in its frontmatter.
Facts (dates, amounts, eligibility, helpline numbers) are copied from the page, never from memory
(CLAUDE.md §1).

**Link status** was checked on 2026-10-24 from a non-Indian network:
- ✅ responded 200 (with redirects followed)
- ⏳ timed out from here. Many Indian government sites block or throttle foreign traffic, so open it from India before relying on it.
- ⚠️ the portal returns 200 for any address, so this specific page couldn't be confirmed. Open it in a browser.

Before writing a corpus document from a ⏳ or ⚠️ source, open it in a browser and confirm the page exists and is current.

## Exams and admissions (after class 5, 8, 10, 12)

| Topic | Source | Status |
|---|---|---|
| National Testing Agency: all national entrance exams | <https://nta.ac.in> | ✅ |
| NEET-UG (medicine) | <https://neet.nta.nic.in> | ✅ |
| JEE Main (engineering) | <https://jeemain.nta.nic.in> | ✅ |
| CUET-UG (central universities) | <https://cuet.nta.nic.in> | ✅ |
| Sainik School entrance (AISSEE) | <https://exams.nta.nic.in/sainik-school-society/> | ✅ |
| Jawahar Navodaya Vidyalaya admission (class 6, 9) | <https://navodaya.gov.in> | ✅ |
| UPSC: civil services, NDA, other exams | <https://upsc.gov.in> | ✅ |
| Staff Selection Commission | <https://ssc.gov.in> | ✅ |
| Indian Army recruitment (Agniveer, officers) | <https://joinindianarmy.nic.in> | ✅ |
| Indian Navy recruitment | <https://joinindiannavy.gov.in> | ⏳ |
| Agniveer Vayu (Air Force) | <https://agnipathvayu.cdac.in> | ⏳ (503 from here) |
| NIOS: open schooling, for students out of regular school | <https://nios.ac.in> | ✅ |
| IGNOU: open university | <https://www.ignou.ac.in> | ✅ |
| CBSE | <https://cbse.gov.in> | ✅ |

## Scholarships

| Topic | Source | Status |
|---|---|---|
| National Scholarship Portal: central and state scholarships | <https://scholarships.gov.in> | ✅ |
| NSP scholarship list | <https://scholarships.gov.in/All-Scholarships> | ✅ |
| NMMS (National Means-cum-Merit Scholarship) | <https://www.myscheme.gov.in/schemes/nmmss> | ⚠️ |
| PM YASASVI | <https://www.myscheme.gov.in/schemes/pm-yasasvi> | ⚠️ |
| INSPIRE (science scholarships and awards) | <https://online-inspire.gov.in> | ✅ |
| INSPIRE-SHE | <https://www.myscheme.gov.in/schemes/inspire-she> | ⚠️ |
| PM Vidyalaxmi (education loans) | <https://pmvidyalaxmi.co.in> | ✅ |
| myScheme: searchable government scheme portal | <https://www.myscheme.gov.in> | ✅ |
| Ministry of Social Justice (SC/OBC scholarships) | <https://socialjustice.gov.in> | ✅ |

## Sports

| Topic | Source | Status |
|---|---|---|
| Khelo India | <https://kheloindia.gov.in> | ✅ |
| Khelo India Scholarship / athlete support | <https://www.myscheme.gov.in/schemes/kis> | ⚠️ |
| Sports Authority of India: training centres, trials | <https://sportsauthorityofindia.nic.in> | ✅ |
| Ministry of Youth Affairs and Sports | <https://yas.gov.in> | ✅ |
| Fit India | <https://www.fitindia.gov.in> | ⏳ |

## Entrepreneurship and livelihoods

| Topic | Source | Status |
|---|---|---|
| Atal Innovation Mission: Atal Tinkering Labs in schools | <https://aim.gov.in> | ✅ |
| Startup India | <https://www.startupindia.gov.in> | ✅ |
| PMEGP (loans for micro-enterprises) | <https://pmegp.in> | ✅ |
| PMEGP scheme page | <https://www.myscheme.gov.in/schemes/pmegp> | ⚠️ |
| Ministry of MSME | <https://msme.gov.in> | ✅ |
| NABARD: rural and agri enterprise | <https://www.nabard.org> | ✅ |
| KVIC: village industries | <https://www.kviconline.gov.in> | ⏳ |

## Public service and public policy

| Topic | Source | Status |
|---|---|---|
| UPSC civil services | <https://upsc.gov.in> | ✅ |
| PRS LAMP Fellowship (working with MPs) | <https://prsindia.org/lamp> | ✅ |
| National Service Scheme (NSS) | <https://nss.gov.in> | ✅ |
| MyGov: citizen participation, quizzes, internships | <https://www.mygov.in> | ✅ |
| National Portal of India | <https://www.india.gov.in> | ✅ |

## Skilling and vocational paths

| Topic | Source | Status |
|---|---|---|
| Skill India Digital Hub | <https://www.skillindiadigital.gov.in/home> | ✅ |
| PMKVY (short-term skill training) | <https://www.myscheme.gov.in/schemes/pmkvy-stt> | ⚠️ |
| PMKVY official site | <https://www.pmkvyofficial.org> | ⏳ |
| DGT: ITIs and apprenticeships | <https://dgt.gov.in> | ⏳ |
| National Career Service (jobs, counselling) | <https://www.ncs.gov.in> | ✅ |
| AICTE (diplomas, engineering colleges) | <https://www.aicte-india.org> | ✅ |
| UGC | <https://www.ugc.gov.in> | ✅ |

## Science, space, agriculture, design (exposure fields)

| Topic | Source | Status |
|---|---|---|
| ISRO: careers, student programmes | <https://www.isro.gov.in> | ✅ |
| DRDO | <https://www.drdo.gov.in> | ⏳ |
| ICAR: agriculture education and research | <https://icar.org.in> | ✅ |
| NIFT (fashion) | <https://www.nift.ac.in> | ✅ |
| NID (design) | <https://nid.edu> | ✅ |

## Curriculum (grounds the Exposure layer)

| Topic | Source | Status |
|---|---|---|
| NCERT textbooks: chapter names per class and subject | <https://ncert.nic.in/textbook.php> | ⏳ |
| DIKSHA: state curriculum content | <https://diksha.gov.in> | ✅ |
| SWAYAM: free online courses | <https://swayam.gov.in> | ✅ |
| Ministry of Education | <https://www.education.gov.in> | ✅ |

## Safety and helplines (crisis replies, S7: copy numbers only from these pages)

| Topic | Source | Status |
|---|---|---|
| Tele-MANAS: national mental-health helpline | <https://telemanas.mohfw.gov.in> | ✅ |
| Ministry of Women and Child Development: child protection, Mission Vatsalya, Childline | <https://wcd.gov.in> | ✅ |
| National Commission for Women | <https://ncw.nic.in> | ⏳ |
| NHRC | <https://nhrc.nic.in> | ✅ |

## Corpus document format (target for S11)

```markdown
---
title: NMMS scholarship — eligibility and how to apply
source_url: https://…
retrieved_on: 2026-10-31
topic: scholarships
grades: [8]
keywords: [NMMS, scholarship, class 8, merit]
---
<Plain-language summary of the page, only facts stated on it.>
```
