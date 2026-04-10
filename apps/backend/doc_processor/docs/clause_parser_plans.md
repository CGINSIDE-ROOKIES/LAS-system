I am defining 조, 항 for contracts as clause, subclause
we are not mentioning or going to use 호, 목 which is under 조, 항

This is based on the document-processor's DocIR datatype

**process overview**:
1. read contract papers (korean, mostly legal/labor related), reject analysis if it's not a relevant document
2. parse/label per-clause/subclause (perform RAG, DB is already prepared)
3. annotate problematic parts. (low, medium, high, critical) performing risk analysis on the documents (planned later on: refer to template/standard contract documents and also suggest formatting/structural changes)
4. suggest edits (display/return diff)
5. user can perform feedbacks and iterate
6. user accepts edit and edit is applied to document


**regarding process 2**:
how it'll parase (per cause/subclause) and also structure/label sections in the doc

"sticky" regex phase
1. parser would start scanning from top to bottom - search whole paragraph text
2. it'll look for the first top-level numbering
   with fallbacks if none found in entire doc: 제X조 -> 1. -> {other clause numbering styles in-order of how common it is}
3. whatever numbering method is found first is going to be the "clause numbering" system for the doc
4. any text coming after Clause numbering detection is going to be under that clause.

so for example:
```
's1.p7.r1': '...',  # NONE
's1.p8.r1': '제1조 (목적) ',  # Clause-1
's1.p8.r2': '이 부속합의서의 목적은 ',  # Clause-1
's1.p8.r3': '대중문화예술기획업자(이하 ‘기획업자’라 한다)와 청소년 대중문화예술인(또는 청소년 연습생, 이하 ‘대중문화예술인’이라 한다)', # Clause-1
...
's1.p11.r1': '제2조 (적용) ',  # Clause-2
 's1.p11.r2': '이 부속 합의서는 별도의 계약을 구성하고 있으며, 주계약 보다 우선',  # Clause-2
 's1.p11.r3': ' 적용된다.',  # Clause-1
```
5. Same pattern would apply for Subclause but within the scope of the same Clause and also a different numbering ruleset.
```
's1.p15.r1': '제4조 (청소년의 학습권 보장) ',  # Clause-4
 's1.p15.r2': '① 기획업자는 ',  # Clause-4 Subclause-1
 's1.p15.r3': '대중문화예술인',  # Clause-4 Subclause-1
 's1.p15.r4': '이 「교육기본법」 제8조에 따른',  # Clause-4 Subclause-1
 's1.p15.r5': ' 의무교육을 받을 권리를 보장하여야 한다.',  # Clause-4 Subclause-1
 's1.p16.r1': '② 기획업자는 대중문화예술인이 의무교육 외의 「초ㆍ중등교육법」 에 따른 학교교육을 받을 것을 원할 경우 이에 협조하여야 한다.',  # Clause-4 Subclause-2
 's1.p17.r1': '③ 기획업자는 대중문화예술인에게 학교의 결석이나 자퇴 등을 강요하여 학습권을 침해하는 행위를 하여서는 아니 된다.',  # Clause-4 Subclause-3
 's1.p19.r1': '제5조 (청소년의 인격권 보장) ',  # Clause-5
```

Note that clause/subclause mix might accur within the same paragraph or runs, so a metadata should be included for ParagraphIR mentioning the Clause/Subclause and the string slice/range info. (need to think of how to deal with labeling tables and images - though unlikely they'll be split)

since this is trailing the last known numbering, if the numbered section completely changes or ends, it can unknowingly number parts after that. gonna solve this via LLMs or maybe other suggestions/idea you might have

if numbering rulesets for those two can be standardized and saved seperately, it'll be better to edit/add/remove rules.

**notes**:
- Langgraph is probably going to be our preferred method
- the whole process is later going to interact via API, integrated into apps/backend/api so keep that in mind (either a wrapper or dep injected). for now after purely testing the pipeline graph then we consider
- as of current (first groundbreaking) doc_processor's dirs are just prev. remnants and temp dir used for testing, you can restructure/delete/create them how you want.
- preference is having a seperate prompts dir and an llm factory for returning appropriate models based on envs.
- models used are going to be: openAI, gemini, other openAI compatible self-hosted models.
- make sure for the LLM payloads, prefix caching would work well


- [] phase 1: implement 1~2 - linear, regex graph part
- [] phase 2: implement 3 - LLM labeling w/structured outputs (multiple worker fan-out)
- [] phase 3: implement 4~6 - Human-in-the-loop w/ tool calling (file edits and annotations)
- [] phase 4: (extra) template based formatting system
