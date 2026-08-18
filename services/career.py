"""services/career.py — resume tailoring, cover letters, interview prep,
salary research. Ported from JARVIS_V5's services/career.py; FRIDAY had
no equivalent.

Uses friday_brain._call_anthropic() directly (see services/legal.py's
docstring for why — think() truncates past ~400 chars, wrong for a real
resume rewrite or cover letter) and core/tools/search.py's cascade for
salary_research() instead of JARVIS's core.tools.web.
"""
from core.friday_brain import friday_brain, MODELS

_SYSTEM = "You are an experienced career coach and resume writer."


def _call(prompt: str, max_tokens: int = 1024) -> str:
    result = friday_brain._call_anthropic(
        [{"role": "user", "content": prompt}], _SYSTEM, MODELS["deep"], max_tokens=max_tokens,
    )
    if not result:
        return "Couldn't reach the model for this right now, boss — try again in a bit."
    return result["content"]


class CareerAssistant:

    def optimize_resume(self, resume: str, job_description: str) -> dict:
        result = _call(
            f"Job Description:\n{job_description[:1000]}\n\nResume:\n{resume[:2000]}\n\n"
            f"Analyze:\n1. Keywords in JD missing from resume\n2. Experience to emphasize\n"
            f"3. Specific resume improvements\n4. Match score (0-100%)\n"
            f"5. Rewritten resume summary for this role",
            max_tokens=1500,
        )
        return {"optimization": result}

    def cover_letter(self, resume: str, job_description: str, company: str) -> str:
        return _call(
            f"Write a compelling, personalized cover letter for:\n"
            f"Company: {company}\nJob: {job_description[:500]}\nBased on resume: {resume[:1000]}\n\n"
            f"Make it genuine, specific, and memorable. Not generic. Not sycophantic.",
            max_tokens=800,
        )

    def interview_prep(self, job_description: str, company: str) -> dict:
        questions = _call(
            f"Generate 10 likely interview questions for:\nCompany: {company}\nRole: {job_description[:500]}\n\n"
            f"Include: behavioral, technical, and culture fit. Add ideal answer frameworks.",
            max_tokens=1500,
        )
        return {"company": company, "questions": questions}

    def salary_research(self, role: str, location: str = "") -> dict:
        from core.tools.web import search
        results = search(f"{role} salary {location}", max_results=5)
        context = "\n".join(r.get("snippet", "") for r in results)
        analysis = _call(
            f"Summarize salary data for {role} in {location}:\n{context}\n\n"
            f"Give: median, range, factors affecting pay, negotiation tips.",
            max_tokens=600,
        )
        return {"role": role, "location": location, "analysis": analysis}


career = CareerAssistant()
