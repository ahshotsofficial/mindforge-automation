#!/usr/bin/env python3
"""
Mindforge - Daily YouTube Shorts content generator
===================================================
Generates one 60-second psychology video package per day:
  - Video idea + hook
  - Title (3 options)
  - Hashtags / tags
  - YouTube description
  - 5-scene silent stickman visual script with exact text overlays for CapCut

Output:  content/YYYY-MM-DD.md  +  content/YYYY-MM-DD.json
State:   content/state.json   (used topics + per-date topic map, so nothing repeats)

Runs with ZERO external dependencies (Python 3.8+ stdlib only), so it works
flawlessly in GitHub Actions with no pip install step.

Optional: set OPENAI_API_KEY to have an LLM write the copy instead of the
built-in template engine. Falls back to the local engine automatically.
"""

import hashlib
import json
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
CONTENT_DIR = ROOT / "content"
CONTENT_DIR.mkdir(exist_ok=True)
STATE_FILE = CONTENT_DIR / "state.json"

# ---------------------------------------------------------------------------
# Content bank: 48 evergreen psychology concepts.
# Each entry feeds the 5-scene template engine. 48 topics x multiple title/hook
# variants = several years of non-repeating daily content.
# ---------------------------------------------------------------------------
BANK = [
    {
        "topic": "Dopamine Detox",
        "misconception": "Dopamine is the pleasure chemical.",
        "truth": "Dopamine is about WANTING, not liking. Your brain fires it before the reward, chasing it.",
        "mechanism": "Every scroll, ping and like gives a tiny dopamine spike. Nothing satisfies — so you scroll again. The loop, not the pleasure, is the product.",
        "evidence": "A 2020 Cambridge study on compulsive checking found reward prediction errors spike even when users reported feeling bored.",
        "action": "Delay your first phone check by 30 minutes tomorrow. Notice the itch. That's the loop."
    },
    {
        "topic": "Negativity Bias",
        "misconception": "Bad days mean a bad life.",
        "truth": "Your brain weights negative events ~5x heavier than positive ones. It's a survival feature.",
        "mechanism": "Ancestors who ignored a rustling bush died. You inherited a brain that treats a rude email like a predator.",
        "evidence": "Baumeister's classic 'Bad is stronger than good' review (2001) found negative info is processed more thoroughly across every domain studied.",
        "action": "Write down 3 things that went right tonight. It's not cringe — it's counterweight."
    },
    {
        "topic": "Spotlight Effect",
        "misconception": "Everyone noticed you tripped.",
        "truth": "Nobody is watching you. They're busy worrying that YOU'RE watching THEM.",
        "mechanism": "Your brain treats your perspective as the center of the world. It forgets everyone else has their own spotlight.",
        "evidence": "Gilovich et al. (2000): students wearing an embarrassing t-shirt guessed 46% of the room noticed. Actual number: ~23%.",
        "action": "Next time you feel judged, ask: 'What was I thinking about THAT stranger yesterday?' Exactly."
    },
    {
        "topic": "Implementation Intentions",
        "misconception": "You need more willpower.",
        "truth": "You don't need motivation. You need a pre-decided IF-THEN plan.",
        "mechanism": "'If X happens, I will do Y' moves the choice from the moment of weakness to right now, when you're strong.",
        "evidence": "Gollwitzer & Sheeran's meta-analysis of 94 studies: if-then plans had a medium-to-large effect on goal achievement.",
        "action": "Replace 'I'll exercise more' with 'If it's 7am, I put on my shoes.' That's the whole trick."
    },
    {
        "topic": "The Zeigarnik Effect",
        "misconception": "Unfinished tasks fade away.",
        "truth": "Your brain keeps unfinished tasks open like 40 browser tabs — on purpose.",
        "mechanism": "Open loops create cognitive tension. That's why cliffhangers work and why you can't relax with a messy to-do list.",
        "evidence": "Waiters remember unpaid orders perfectly — and forget them seconds after the bill is paid. Zeigarnik, 1927.",
        "action": "Can't focus? Write the unfinished task on paper. The loop closes. Your RAM frees up."
    },
    {
        "topic": "Emotional Granularity",
        "misconception": "You're just 'stressed'.",
        "truth": "People who name emotions precisely (not 'bad' — 'resentful') regulate them dramatically better.",
        "mechanism": "A vague emotion feels like weather. A precise label becomes a problem you can solve. Language IS regulation.",
        "evidence": "A 2017 Emotion journal study found higher emotional granularity predicted lower escalation into depression after stressful events.",
        "action": "Right now, name this week's feeling in one specific word. Not 'bad'. Go."
    },
    {
        "topic": "Hedonic Adaptation",
        "misconception": "The new phone will make you happy.",
        "truth": "Every upgrade becomes your boring baseline within weeks. Your brain resets happiness to neutral.",
        "mechanism": "Evolution can't let you stay satisfied — satisfaction stops the striving that kept ancestors alive. You're built to adapt.",
        "evidence": "Lottery winners and paraplegics converged to near-baseline happiness within a year — Brickman's famous 1978 study.",
        "action": "Want more joy? Don't add. Pause and subtract familiarity: skip your favorite thing for 2 weeks."
    },
    {
        "topic": "The Mere Exposure Effect",
        "misconception": "You like what's good.",
        "truth": "You like what's FAMILIAR. Familiarity itself gets mistaken for goodness.",
        "mechanism": "Your brain reads easy-processing as safe, and safe as good. Repetition literally manufactures liking.",
        "evidence": "Zajonc (1968): repeating random shapes and nonsense words to people made them rate the meaningless items more positively.",
        "action": "Advertisers know this. Ask yourself: do I love this brand, or have I just seen it 400 times?"
    },
    {
        "topic": "Decision Fatigue",
        "misconception": "You're lazy after 3pm.",
        "truth": "Every decision drains the same fuel tank. By evening, your brain picks whatever's easiest.",
        "mechanism": "Judges grant parole ~65% at the start of sessions and near 0% before breaks. Not cruel — depleted.",
        "evidence": "Danziger et al. (2011), PNAS: favorable rulings peaked at session start and dropped to near-zero before food breaks.",
        "action": "Decide tonight: clothes, breakfast, first task. Save your 3pm brain from your 9am brain."
    },
    {
        "topic": "Social Contagion",
        "misconception": "Your mood is only yours.",
        "truth": "Emotions spread through your network like a virus — up to 3 people away from you.",
        "mechanism": "Mirror systems copy micro-expressions, tone and posture automatically. Your face is a broadcast tower.",
        "evidence": "Framingham Heart Study data (Fowler & Christakis, 2008): happiness clusters spread through 3 degrees of social connection.",
        "action": "You can't control everything you feel. But you control who you stand next to. Choose carefully."
    },
    {
        "topic": "Loss Aversion",
        "misconception": "You choose logically.",
        "truth": "Losing $100 hurts about twice as much as gaining $100 feels good.",
        "mechanism": "Your ancestors couldn't afford a bad bet. Modern result: you stay in bad jobs, bad relationships, bad stocks — because leaving feels like loss.",
        "evidence": "Kahneman & Tversky's prospect theory (1979) — the research that eventually won a Nobel Prize.",
        "action": "Stuck on a decision? Ask: 'If I were already out of this, would I choose back in?' That's your answer."
    },
    {
        "topic": "The Peak-End Rule",
        "misconception": "Your memory records experiences accurately.",
        "truth": "You only remember 2 things: the emotional peak, and how it ended.",
        "mechanism": "Your brain compresses hours into snapshots. A fine vacation with a bad ending gets stored as a bad vacation.",
        "evidence": "Kahneman's cold water experiment: people chose to repeat a LONGER unpleasant experience if it ended slightly warmer.",
        "action": "Design your endings. Last 5 minutes of a date, a meeting, a day — that's the whole memory."
    },
    {
        "topic": "Cognitive Dissonance",
        "misconception": "You change your behavior to match your beliefs.",
        "truth": "It's usually the reverse: you change your beliefs to match your behavior.",
        "mechanism": "Holding two conflicting ideas is physically uncomfortable. The cheapest fix is rewriting what you believe.",
        "evidence": "Festinger & Carlsmith (1959): paid $1 to lie that a boring task was fun, subjects actually started believing it. Paid $20? Didn't.",
        "action": "Notice when you justify. That discomfort you're smoothing over? That's the signal worth listening to."
    },
    {
        "topic": "Parasympathetic Breathing",
        "misconception": "Calm comes from the mind.",
        "truth": "You can hack anxiety directly through the body. Exhale longer than you inhale.",
        "mechanism": "Long exhales activate the vagus nerve, which tells your heart to slow down. Mind follows body — not just the other way.",
        "evidence": "A 2017 Frontiers in Psychology review: slow breathing protocols reliably reduced cortisol and increased relaxation markers.",
        "action": "Inhale 4 seconds. Exhale 8. Do it 5 times. That's a nervous system reset, no app required."
    },
    {
        "topic": "The Dunning-Kruger Effect",
        "misconception": "Confident people are competent.",
        "truth": "Beginners often feel MOST confident — because they don't know enough to see their own gaps.",
        "mechanism": "The skills needed to be good at something are the same skills needed to judge if you're good at it. Beginners can't judge.",
        "evidence": "Kruger & Dunning (1999): lowest-quartile test takers estimated their rank near the 60th percentile. Actual: ~12th.",
        "action": "Feeling like an impostor? That's usually what growth feels like. The confident beginner is the one to worry about."
    },
    {
        "topic": "Habit Stacking",
        "misconception": "New habits need new time slots.",
        "truth": "The easiest habit to build attaches to one you already have.",
        "mechanism": "Existing habits are established neural highways. Piggybacking skips the hardest part: remembering.",
        "evidence": "A 2019 framework from BJ Fogg's Stanford Behavior Lab: anchoring new behaviors to existing routines doubled adherence vs. time-based cues.",
        "action": "Formula: 'After I [existing habit], I will [tiny new habit].' After coffee, one pushup. That's it."
    },
    {
        "topic": "Ego Depletion Myth",
        "misconception": "Willpower is a muscle that runs out.",
        "truth": "It's more like a mindset. People who BELIEVE willpower is unlimited actually perform better late in the day.",
        "mechanism": "Your beliefs about fatigue set your limits. Repeated studies show the 'tank' refills when you think it does.",
        "evidence": "Job, Dweck & Walton (2010): people who believed willpower was abundant showed no afternoon performance drop.",
        "action": "That 'I'm too tired to start' voice at 8pm? Test it. Start for 2 minutes. Watch the tank refill."
    },
    {
        "topic": "The Takeaway Effect",
        "misconception": "Scarcity tricks are only for sales.",
        "truth": "Your brain values anything about to be taken away — including people, roles, and identities.",
        "mechanism": "Loss looms larger than gain. Psychological reactance kicks in when freedom shrinks: 'I want it MORE now that I can't have it.'",
        "evidence": "Worchel's cookie jar study (1975): cookies in a nearly empty jar were rated tastier than identical cookies in a full one.",
        "action": "Notice the pull when something becomes scarce — a job offer deadline, a distant ex. Is it real value, or just loss?"
    },
    {
        "topic": "Sleep & Memory Consolidation",
        "misconception": "Sleep is downtime.",
        "truth": "While you sleep, your brain replays the day at high speed and files what matters.",
        "mechanism": "During deep sleep, the hippocampus re-broadcasts the day's memories to the cortex for long-term storage. All-nighters delete the work you did.",
        "evidence": "A 2021 Nature study: participants who slept after learning showed ~40% better recall than those who stayed awake — same study time.",
        "action": "Studying for something important? Review it right before bed. Sleep is your study session's second half."
    },
    {
        "topic": "Anchoring",
        "misconception": "You estimate prices and numbers independently.",
        "truth": "The first number you see drags every later judgment toward it — even random ones.",
        "mechanism": "Your brain adjusts away from the anchor, but never adjusts far enough. Every negotiator knows this.",
        "evidence": "Kahneman: a rigged roulette wheel landed on 10 — participants' guesses of African UN nations dropped by ~10 countries versus a wheel showing 65.",
        "action": "Before any negotiation, set YOUR anchor first — even in your head. Never let them place the first number."
    },
    {
        "topic": "The Progress Principle",
        "misconception": "Motivation comes from purpose.",
        "truth": "The single biggest motivator is small, visible PROGRESS in meaningful work.",
        "mechanism": "Progress triggers a positive feedback loop: progress → better mood → better work → more progress. Tiny wins compound.",
        "evidence": "Amabile & Kramer analyzed ~12,000 workday diary entries: 'making progress' topped the inner-work-life motivators, far above recognition.",
        "action": "End each workday by writing one line of visible progress. Momentum is a file you maintain."
    },
    {
        "topic": "Egocentric Bias",
        "misconception": "You remember your contributions accurately.",
        "truth": "You systematically overestimate how much YOU did — in every group, every project, every household.",
        "mechanism": "Your own effort is fully visible to you. Everyone else's work is invisible unless you look. So your ledger inflates.",
        "evidence": "Ross & Sicoly (1978): spouses' estimates of their share of household work summed to well over 100%.",
        "action": "Before you say 'I did everything', assume your mental ledger is inflated. It is. Thank someone specific today."
    },
    {
        "topic": "The Paradox of Choice",
        "misconception": "More options = more freedom = more happiness.",
        "truth": "Beyond ~a handful of options, more choice creates paralysis and regret — not satisfaction.",
        "mechanism": "Every option carries imagined trade-offs. With 57 choices, even a great pick feels like you lost 56 others.",
        "evidence": "Iyengar & Lepper's jam study (2000): 24 jam options drew more browsers; 6 options sold ~10x more.",
        "action": "For big decisions, cut the menu to 3. 'Good enough' beats 'best' — because 'best' doesn't exist under 57 tabs."
    },
    {
        "topic": "Post-Traumatic Growth",
        "misconception": "Trauma only destroys.",
        "truth": "A majority of trauma survivors report at least one domain of positive growth afterward.",
        "mechanism": "Suffering shatters assumptions. Rebuilding them — deliberately — can produce deeper relationships, new priorities, and real strength.",
        "evidence": "Tedeschi & Calhoun's research: 50–70% of trauma survivors report growth in at least one of five life domains.",
        "action": "Not every wound is a gift — but the question 'who am I becoming because of this?' is worth asking. Ask it."
    },
    {
        "topic": "Temptation Bundling",
        "misconception": "You must separate work from fun.",
        "truth": "Pair a 'should' with a 'want' and the 'should' inherits the pull.",
        "mechanism": "Instant gratification is the strongest force in habit design. Bundle it with delayed payoffs and both fire at once.",
        "evidence": "Milkman's gym study (2014): tempting audiobooks ONLY available at the gym increased gym visits by 51%.",
        "action": "Only listen to your favorite podcast while walking. Only that show while doing chores. Design the bundle."
    },
    {
        "topic": "Illusion of Transparency",
        "misconception": "People can tell you're nervous.",
        "truth": "Your inner state is far less visible than you think. Nobody can hear your thoughts.",
        "mechanism": "You experience your feelings at full volume from the inside. Observers only get a tiny, easily-masked external signal.",
        "evidence": "Gilovich (1998): speakers rated their nervousness 6.5/10; audience estimates averaged ~5.25 — and predicted quality just fine.",
        "action": "That shaking-hands feeling before you present? They can't see it. Walk in like it's true — because it is."
    },
    {
        "topic": "Fundamental Attribution Error",
        "misconception": "People who cut you off are jerks.",
        "truth": "You judge others by their actions but yourself by your circumstances.",
        "mechanism": "When others fail, you see character. When you fail, you see context. The same brain, the same event, opposite explanations.",
        "evidence": "Ross (1977) named the bias; dozens of studies confirm we overweight disposition and underweight situation for others' behavior.",
        "action": "Next time someone's 'being difficult', generate 2 situational explanations first. Then respond to the more human one."
    },
    {
        "topic": "Cognitive Reappraisal",
        "misconception": "You feel what you feel — period.",
        "truth": "Between event and emotion sits interpretation. Change the interpretation, change the emotion.",
        "mechanism": "The same arousal reads as excitement or anxiety depending on the story you attach. The body doesn't choose the label — you do.",
        "evidence": "Brooks (2014): people who relabeled anxiety as 'excitement' before public speaking outperformed those told to 'calm down'.",
        "action": "Racing heart before something big? Say: 'This is energy.' Your body believes you."
    },
    {
        "topic": "The Fresh Start Effect",
        "misconception": "New habits should start... whenever.",
        "truth": "Temporal landmarks — Mondays, birthdays, New Year — measurably boost follow-through.",
        "mechanism": "Landmarks create a 'new me' narrative. The old self 'failed'; the new self is unburdened by that ledger.",
        "evidence": "Dai, Milkman & Riis (2014): Google searches for 'gym' spiked ~82% above baseline right after temporal landmarks.",
        "action": "Don't wait for motivation. Wait for a landmark — or manufacture one: 'New chapter starts Tuesday, March 3.'"
    },
    {
        "topic": "Platonic Cueing / Power Posing",
        "misconception": "Body language is only about how others see you.",
        "truth": "Your posture feeds back into your own hormones and confidence — slightly, but measurably.",
        "mechanism": "Expansive postures are associated with small shifts in felt confidence and reduced cortisol in several replications.",
        "evidence": "Carney et al. (2010) found posture shifts in hormones; 2 minutes of expansion before a task is the honest, replicated takeaway.",
        "action": "Before a hard conversation, stand tall for 2 minutes alone. Not magic — a small, free edge."
    },
    {
        "topic": "The Fundamental Need for Autonomy",
        "misconception": "Rewards are the best motivator.",
        "truth": "Control over your own time and choices beats money for long-term motivation.",
        "mechanism": "Self-Determination Theory: autonomy, competence, relatedness. Autonomy comes first — remove it and intrinsic drive collapses.",
        "evidence": "A large 2017 meta-analysis (Deci et al.) confirmed tangible rewards undermine intrinsic motivation for interesting tasks.",
        "action": "Feeling burnt out? It may not be the work. It may be that you have zero say in HOW you do it. Fix the second thing."
    },
    {
        "topic": "Time Affluence",
        "misconception": "Money buys happiness directly.",
        "truth": "Buying TIME — outsourcing chores you hate — reliably raises life satisfaction more than buying stuff.",
        "mechanism": "Feeling 'time-poor' is one of the strongest negative predictors of well-being. Stuff doesn't fix it; minutes do.",
        "evidence": "Whillans et al. (2017, PNAS): people who spent money on time-saving services reported greater life satisfaction, replicated across countries.",
        "action": "Before your next impulse buy, ask: could this money buy me back 3 hours instead? Hours win."
    },
    {
        "topic": "The Spotlight of Comparison",
        "misconception": "Instagram shows you how well others are doing.",
        "truth": "It shows you their highlight reel — and you compare it to your behind-the-scenes. Rigged game.",
        "mechanism": "Upward social comparison against curated data triggers envy and self-doubt. The data itself is false.",
        "evidence": "A 2018 University of Pennsylvania experiment: limiting social media to 30 min/day reduced loneliness and depression in 3 weeks.",
        "action": "Compare yourself to your last 6 months. That's the only fair dataset. Unfollow the rest."
    },
    {
        "topic": "The Emotional Contagion of Loneliness",
        "misconception": "Loneliness is just being alone.",
        "truth": "Loneliness is a biological alarm — as dangerous as smoking 15 cigarettes a day.",
        "mechanism": "Perceived isolation triggers hypervigilance, inflammation and worse sleep. The body treats it like starvation.",
        "evidence": "Holt-Lunstad's meta-analysis (2010, 148 studies): weak social ties raised mortality risk ~50% — comparable to smoking and obesity.",
        "action": "Text one person right now. Not to network. Just to be someone's third-degree connection. It literally adds time."
    },
    {
        "topic": "Attention Residue",
        "misconception": "Multitasking makes you efficient.",
        "truth": "Switching tasks leaves mental residue: part of your brain stays stuck on the last task for 20+ minutes.",
        "mechanism": "Every tab-switch leaves unfinished processing behind. The cost isn't the switch — it's the residue after it.",
        "evidence": "Sophie Leroy (2009): performance on the next task dropped unless the previous task was fully closed off.",
        "action": "Batch your checking. Phone, email, Slack — 3 fixed windows a day. Between them, one tab. Be boring, be fast."
    },
    {
        "topic": "Self-Compassion Beats Self-Criticism",
        "misconception": "Being hard on yourself drives improvement.",
        "truth": "Self-criticism predicts procrastination and quitting. Self-compassion predicts trying again.",
        "mechanism": "Harsh self-talk triggers threat mode — fight/flight about yourself. Threat mode is terrible for learning.",
        "evidence": "Breines & Chen (2012): people prompted to be self-compassionate after failure spent MORE time practicing to improve.",
        "action": "Talk to yourself like you'd talk to a friend who failed. Not softness — strategy."
    },
    {
        "topic": "The Effort Heuristic",
        "misconception": "Value is objective.",
        "truth": "You value things more when they look like they took effort — art, food, even people.",
        "mechanism": "Effort signals rarity and care. Your brain uses it as a shortcut for worth, and it can be faked.",
        "evidence": "Kruger et al. (2004): identical poems and paintings rated higher when described as taking more effort to produce.",
        "action": "Beware pricing that flaunts effort ('handmade', 'artisanal'). Judge the thing, not the labor story."
    },
    {
        "topic": "The Midpoint Motivation Spike",
        "misconception": "Motivation declines steadily toward a deadline.",
        "truth": "Progress is slow at the start, surges right after the halfway point, and spikes at the end.",
        "mechanism": "At the midpoint, remaining work finally looks smaller than completed work. The brain's accounting flips.",
        "evidence": "Amit Kabeli & Amar: sushi diners ate faster and more when told they were past the midpoint of their plate.",
        "action": "Feeling stuck early on? Pretend it's the middle. Fake landmarks work on your own brain."
    },
    {
        "topic": "Emotional Labeling (Affect Labeling)",
        "misconception": "Naming a feeling makes it stronger.",
        "truth": "Putting feelings into words reduces amygdala activity — it's free therapy, available 24/7.",
        "mechanism": "Verbalizing engages prefrontal regions that down-regulate the fear center. 'Name it to tame it.'",
        "evidence": "Lieberman (2007): affect labeling while viewing angry faces decreased amygdala response versus watching passively.",
        "action": "Write the emotion in one sentence — 'I feel ashamed because...'. Watch the volume drop in real time."
    },
    {
        "topic": "The Two-Minute Rule",
        "misconception": "Big goals need big starts.",
        "truth": "Shrink every habit to under two minutes. The goal isn't the result — it's becoming the kind of person who starts.",
        "mechanism": "Habits fail at the startup cost, not the workload. A 'read one page' habit keeps the identity alive; volume can grow later.",
        "evidence": "Behavioral research on habit formation (Lally et al., 2010): automaticity depends on repetition consistency far more than intensity.",
        "action": "'Read before bed' fails. 'Read ONE page' works — and pages stack. Start stupidly small tonight."
    },
    {
        "topic": "Revenge Bedtime Procrastination",
        "misconception": "You're just bad at discipline at night.",
        "truth": "Staying up scrolling is a protest. You're reclaiming the daytime that work stole from you.",
        "mechanism": "People with low daytime autonomy sacrifice sleep for a sense of free time. The problem isn't night — it's the day.",
        "evidence": "A 2020 Frontiers in Psychology study: lower daytime control and higher evening self-regulation failure predicted bedtime procrastination.",
        "action": "Guard 30 minutes of genuinely YOUR time during the day. Your nights stop fighting for it back."
    },
    {
        "topic": "The Self-Serving Bias",
        "misconception": "Success and failure are judged fairly.",
        "truth": "You take credit for wins and blame the situation for losses. Everyone does. That's the trap.",
        "mechanism": "Protecting self-esteem feels good short-term but blocks learning — if it's never your fault, there's nothing to fix.",
        "evidence": "Meta-analysis (Mezulis et al., 2004): self-serving attribution exists across cultures, strongest in those with self-esteem to protect.",
        "action": "After your next failure, ask one question: 'What was MY 10%?' Own the 10%. Learn from it."
    },
    {
        "topic": "Flow State",
        "misconception": "Flow comes randomly.",
        "truth": "Flow has an entry formula: a challenge slightly ABOVE your skill, instant feedback, no interruptions.",
        "mechanism": "Too easy = boredom. Too hard = anxiety. The sweet edge between them triggers total absorption.",
        "evidence": "Csikszentmihalyi's experience sampling of thousands: flow reports clustered precisely at the challenge-skill balance point.",
        "action": "Pick the task version that's 4% too hard. Silence notifications. Timer on. Enter."
    },
    {
        "topic": "The Ben Franklin Effect",
        "misconception": "We help people we like.",
        "truth": "We come to like people we've helped. The action comes first; the feeling follows.",
        "mechanism": "Your brain needs a story for why you did a favor. 'I must like them' gets written retroactively.",
        "evidence": "Jecker & Landy (1969): people who'd done a researcher a favor rated him warmer than those he'd done a favor for.",
        "action": "Want to connect with someone? Ask THEM for a small favor. Works on them — and on you."
    },
    {
        "topic": "Anxiety's Useful Secret",
        "misconception": "Anxiety is a malfunction.",
        "truth": "Anxiety is your threat-detection system working — just pointed at the wrong targets.",
        "mechanism": "The system can't tell a deadline from a predator. It raises arousal to make you act. The signal is 'prepare', not 'panic'.",
        "evidence": "A 2019 review: moderate anxiety improves performance on tasks requiring vigilance — the Yerkes-Dodson curve, replicated.",
        "action": "Ask your anxiety: 'What are you telling me to prepare for?' Then actually prepare. Signal received."
    },
    {
        "topic": "Gratitude's Mechanics",
        "misconception": "Gratitude is just positive thinking.",
        "truth": "Gratitude is a memory-training protocol. It forces your brain to re-scan for what's working.",
        "mechanism": "Your attention system filters ruthlessly. A gratitude practice literally reprograms what gets through the filter.",
        "evidence": "Emmons & McCullough (2003): 10 weeks of weekly gratitude lists raised well-being AND optimism versus recording hassles.",
        "action": "Three specific things tonight — not 'family', but 'the way my sister called just to check in'. Specificity is the mechanism."
    },
    {
        "topic": "The Contrast Effect",
        "misconception": "You judge things on their merits.",
        "truth": "You judge everything against whatever came right before it. Order changes reality.",
        "mechanism": "Perception is relative. An average apartment looks great after a terrible one. A compliment lands flat after a great one.",
        "evidence": "Real estate agents showed houses in descending price order rated as more attractive overall (Northcraft & Neale, 1986).",
        "action": "Sequence your life deliberately: hard things first, rewards after. Your brain will rate the rewards higher."
    },
    {
        "topic": "The IKEA Effect",
        "misconception": "Things have fixed value.",
        "truth": "You overvalue anything you helped build — furniture, software, ideas, teams.",
        "mechanism": "Labor creates attachment. Your effort gets woven into the object's worth, inflating it far beyond market value.",
        "evidence": "Norton, Mochon & Ariely (2012): people's willingness to pay for self-assembled IKEA items rose sharply versus identical pre-built ones.",
        "action": "Want people to care about the project? Let them build a part of it. Ownership is manufactured by effort."
    },
]

# ---------------------------------------------------------------------------
# Variant pools (picked deterministically per-day so output varies)
# ---------------------------------------------------------------------------
TITLE_PATTERNS = [
    "The {topic} Trick Your Brain Hides From You",
    "Why {topic} Controls Your Life (Without You Knowing)",
    "Psychologists Beg You To Understand {topic}",
    "{topic}: The 60-Second Explanation That Changes Everything",
    "This Is Why {topic} Feels Unstoppable",
    "Your Brain Uses {topic} Against You — Here's the Fix",
    "The Dark Truth About {topic}",
    "What {topic} Actually Is (Most People Get It Wrong)",
]

HOOKS = [
    "99% of people get this completely backwards.",
    "Your brain is doing this to you right now.",
    "This explains everything about your last bad week.",
    "You were never taught this. You should have been.",
    "Watch this before you blame yourself again.",
    "Psychologists have known this for 40 years.",
    "This one diagram explains your whole mood.",
    "Once you see this, you can't unsee it.",
]

SCENE_TIMES = [(0, 3), (3, 15), (15, 32), (32, 48), (48, 60)]
SCENE_ROLES = ["HOOK", "SETUP", "MECHANISM", "PROOF / CONTRAST", "PAYOFF / CTA"]

MD_TAGS = [
    "psychology", "psychologyshorts", "mindforge", "brainscience", "mentalhealth",
    "neuroscience", "selfimprovement", "psychologyfacts", "humanbehavior", "mindset",
]

# ---------------------------------------------------------------------------
# Deterministic daily selection
# ---------------------------------------------------------------------------
def load_state():
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("used_topics", [])
                data.setdefault("history", [])
                data.setdefault("topics_by_date", {})
                return data
        except json.JSONDecodeError:
            print("[warn] state.json is corrupt; starting with a fresh state.", file=sys.stderr)
    return {"used_topics": [], "history": [], "topics_by_date": {}}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _slug(text):
    """Make a topic safe for hashtags: lowercase, no spaces or special chars."""
    cleaned = "".join(c for c in text.lower() if c.isalnum())
    return cleaned or "psychology"


def pick_topic(state, date_str):
    """Deterministic per date: rotate through the bank, skipping used topics
    until the bank is exhausted (then reset history)."""
    used = state.get("used_topics", [])
    available = [i for i in range(len(BANK)) if BANK[i]["topic"] not in used]
    if not available:  # bank exhausted -> start a new cycle
        available = list(range(len(BANK)))
        used = []
    seed = int(hashlib.sha256(date_str.encode()).hexdigest()[:8], 16)
    idx = available[seed % len(available)]
    return idx, used


def build_package(date_str):
    state = load_state()
    idx, used = pick_topic(state, date_str)
    entry = BANK[idx]
    seed = int(hashlib.sha256((date_str + entry["topic"]).encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    topic = entry["topic"]
    title = TITLE_PATTERNS[seed % len(TITLE_PATTERNS)].format(topic=topic)
    alt_titles = [p.format(topic=topic) for p in TITLE_PATTERNS]
    alt_titles.remove(title)
    rng.shuffle(alt_titles)

    hook = HOOKS[seed % len(HOOKS)]
    topic_slug = _slug(topic)
    tags = sorted(set(MD_TAGS + [topic_slug]))
    tag_str = ", ".join("#" + t for t in tags)

    # ---- 5-scene stickman script (60s total) --------------------------------
    scenes = [
        {
            "role": SCENE_ROLES[0],
            "time": "0:00 - 0:03",
            "duration": "3s",
            "visual": (
                "Stickman stares at viewer, blank face. A question mark pulses above his head. "
                "Black background, single white stick figure, thick lines."
            ),
            "overlay": hook.upper(),
            "overlay_style": "Large bold, white, center screen. Pop-in animation at 0.2s.",
        },
        {
            "role": SCENE_ROLES[1],
            "time": "0:03 - 0:15",
            "duration": "12s",
            "visual": (
                f"Stickman says/thinks the common belief. Show a speech bubble: '{entry['misconception']}' "
                f"Then a red X strikes through it. Stickman's expression changes to confusion."
            ),
            "overlay": entry["misconception"].upper() + "  ✗",
            "overlay_style": "Speech-bubble style text, then red ✗ stamp over it at 0:08.",
        },
        {
            "role": SCENE_ROLES[2],
            "time": "0:15 - 0:32",
            "duration": "17s",
            "visual": (
                "Split screen: left stickman operates on 'auto' (gear icons spinning above head), "
                "right stickman 'sees the loop' (lightbulb). Simple line arrows connect them."
            ),
            "overlay": _wrap(entry["truth"]),
            "overlay_style": "Lower third, medium bold, white with thin black outline, appears at 0:16.",
        },
        {
            "role": SCENE_ROLES[3],
            "time": "0:32 - 0:48",
            "duration": "16s",
            "visual": (
                "Stickman points at a simple chart/blackboard sketch on the wall "
                "(upward line or two contrasting bars). Keep drawing minimal: 2 shapes max."
            ),
            "overlay": _wrap(entry["evidence"], short=True),
            "overlay_style": "Side panel text (right of stickman), medium size, yellow highlight bar behind key words.",
        },
        {
            "role": SCENE_ROLES[4],
            "time": "0:48 - 0:60",
            "duration": "12s",
            "visual": (
                "Stickman performs the action (use a simple matching prop: phone, pen, shoe, bed). "
                "Then he turns to camera, slight nod. Channel name appears."
            ),
            "overlay": _wrap(entry["action"]),
            "overlay_style": "Center screen, bold, white. Then 'MINDFORGE' logo-text fades in bottom center at 0:55.",
        },
    ]

    description = (
        f"{topic} — explained in 60 seconds.\n\n"
        f"{entry['truth']}\n\n"
        f"What actually happens in your brain: {entry['mechanism']}\n\n"
        f"Try it today: {entry['action']}\n\n"
        "Mindforge posts one 60-second psychology explainer every day. "
        "Follow so tomorrow's video finds you.\n\n"
        f"{tag_str}\n\n"
        f"#{topic_slug} #shorts"
    )

    return {
        "date": date_str,
        "channel": "Mindforge",
        "format": "YouTube Short - 60s, 9:16, silent, stickman animation",
        "topic": topic,
        "titles": [title] + alt_titles[:2],
        "title": title,
        "hook": hook,
        "description": description,
        "tags": tags,
        "hashtags": tag_str,
        "scenes": scenes,
        "capcut_notes": [
            "Canvas: 1080x1920 (9:16). Background: solid black (#000000).",
            "Stick figure: white (#FFFFFF), round stroke caps, ~14px stroke, no face details except expression changes.",
            "No voiceover, no music required — but a soft lo-fi loop under 30% volume is allowed.",
            "One text style set: bold sans (Inter Black / Montserrat ExtraBold), white, 2-3px black outline.",
            "Total text on screen never exceeds 2 blocks at once. Max ~12 words per overlay.",
            "Export: 30fps, H.264, bitrate 12-16 Mbps, under 60 seconds for the Shorts feed.",
        ],
    }


def _wrap(text, short=False):
    """Insert a manual line break for CapCut overlays (text stays exact)."""
    words = text.split()
    limit = 6 if short else 8
    lines, line = [], []
    for w in words:
        line.append(w)
        if len(line) >= limit:
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------
def render_markdown(pkg):
    s = pkg["scenes"]
    md = f"""# Mindforge — Daily Short ({pkg["date"]})

**Channel:** Mindforge
**Format:** {pkg["format"]}

---

## 🎯 Video Idea

**Topic:** {pkg["topic"]}

**Hook line:** {pkg["hook"]}

---

## 📌 Titles (pick one)

1. **{pkg["titles"][0]}**
2. {pkg["titles"][1]}
3. {pkg["titles"][2]}

---

## 🏷️ Tags / Hashtags

```
{pkg["hashtags"]}
```

---

## 📝 Description (copy-paste ready)

```
{pkg["description"]}
```

---

## 🎬 5-Scene Stickman Script (silent, 60s, 9:16)

"""
    for i, sc in enumerate(s, 1):
        md += f"""### Scene {i} — {sc["role"]} ({sc["time"]}, {sc["duration"]})

**Stickman visual:** {sc["visual"]}

**Text overlay (exact):**
```
{sc["overlay"]}
```
**Overlay style:** {sc["overlay_style"]}

---

"""
    md += "## ⚙️ CapCut Notes\n\n"
    for note in pkg["capcut_notes"]:
        md += f"- {note}\n"
    return md


# ---------------------------------------------------------------------------
# Optional LLM upgrade (only if OPENAI_API_KEY is set) — otherwise skipped
# ---------------------------------------------------------------------------
def try_llm_enhance(pkg):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return pkg
    try:
        import urllib.request
        prompt = (
            "You are the head writer for 'Mindforge', a psychology YouTube Shorts channel. "
            f"Rewrite this 5-scene stickman script about '{pkg['topic']}' so every text overlay is "
            "punchier (max 12 words each) while keeping the same psychological accuracy and scene timing. "
            "Return ONLY valid JSON with the same schema: keys date, channel, format, topic, titles "
            "(3 strings), title, hook, description, tags (list), hashtags, scenes (list of 5 objects with "
            "role, time, duration, visual, overlay, overlay_style), capcut_notes (list). "
            f"Here is the draft:\n{json.dumps(pkg, ensure_ascii=False)}"
        )
        body = json.dumps({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }).encode()
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions", data=body,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        enhanced = json.loads(data["choices"][0]["message"]["content"])
        # basic schema sanity check before trusting it
        if isinstance(enhanced.get("scenes"), list) and len(enhanced["scenes"]) == 5:
            enhanced["date"] = pkg["date"]
            enhanced["channel"] = "Mindforge"
            return enhanced
    except Exception as e:
        print(f"[warn] LLM enhancement failed ({e}); using local engine output.", file=sys.stderr)
    return pkg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    force = "--force" in sys.argv
    # Use the UTC date so the 06:00 UTC cron always lands on the correct calendar day.
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    state = load_state()
    history = state.get("history", [])
    # Skip only when the day's files actually exist (a lost file is regenerated, not skipped)
    if date_str in history and not force and (CONTENT_DIR / f"{date_str}.md").exists():
        print(f"[skip] Content for {date_str} already generated. Use --force to regenerate.")
        return 0

    # If this date was generated before, its old topic is about to be replaced.
    # Un-mark it as "used" first so the topic bank stays accurate. This fixes the
    # bug where a --force regeneration permanently skipped the replaced topic.
    stale_topic = state.get("topics_by_date", {}).get(date_str)
    if stale_topic and stale_topic in state.get("used_topics", []):
        state["used_topics"] = [t for t in state["used_topics"] if t != stale_topic]
        save_state(state)

    pkg = build_package(date_str)
    pkg = try_llm_enhance(pkg)

    md_path = CONTENT_DIR / f"{date_str}.md"
    json_path = CONTENT_DIR / f"{date_str}.json"
    md_path.write_text(render_markdown(pkg), encoding="utf-8")
    json_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")

    if date_str not in history:
        history.append(date_str)
    state["history"] = history[-400:]
    state["used_topics"] = list({
        *state.get("used_topics", []),
        pkg["topic"],
    })
    # Per-date topic map: lets a later --force regen know exactly which topic it
    # is replacing (kept in sync with the trimmed history window).
    topics_by_date = state.get("topics_by_date", {})
    topics_by_date[date_str] = pkg["topic"]
    state["topics_by_date"] = {d: t for d, t in topics_by_date.items() if d in state["history"]}
    if len(state["used_topics"]) >= len(BANK):
        state["used_topics"] = [pkg["topic"]]  # start a new cycle
        state["topics_by_date"] = {date_str: pkg["topic"]}
    save_state(state)

    print(f"[ok] {date_str}: {pkg['topic']}")
    print(f"     -> {md_path}")
    print(f"     -> {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
