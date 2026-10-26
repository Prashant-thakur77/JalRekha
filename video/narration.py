"""The narrator's lines as data: (scene, id, caption, spoken, exaggeration, cfg).

The caption keeps the real spelling ("10.6 cm", "NadiSaathi"); the spoken text is respelled for the voice
("ten point six centimetres", "Nadi Saathi"). Numbers come from facts.py, never typed here.
Story lines are read slower and softer (lower cfg), product lines brisker.
"""

from __future__ import annotations

from facts import F

STORY = (0.6, 0.3)
PRODUCT = (0.6, 0.45)

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def words(n: int) -> str:
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + ONES[n % 10])
    if n < 1000:
        rest = n % 100
        return ONES[n // 100] + " hundred" + ("" if rest == 0 else " and " + words(rest))
    return words(n // 1000) + " thousand" + ("" if n % 1000 == 0 else " " + words(n % 1000))


def say(value: str) -> str:
    """'10.6' -> 'ten point six', '103' -> 'one hundred and three'."""
    v = value.strip("$%")
    if "." in v:
        a, b = v.split(".")
        return words(int(a)) + " point " + " ".join(ONES[int(d)] for d in b)
    return words(int(v))


LINES: list[tuple[str, str, str, str, tuple[float, float]]] = [
    # --- the story (photos of the 2008 Kosi flood and the Koshi barrage; licensed, credited on screen)
    ("story", "s1", "Two in the morning, in Supaul, Bihar. The Koshi is rising.",
     "Two in the morning, in Supaul, Bihar. The Koshi is rising.", STORY),
    ("story", "s2", "The water started in Nepal's hills, hours ago.",
     "The water started in Nepal's hills, hours ago.", STORY),
    ("story", "s3", "Upstream, a gauge reader writes the level by hand. Downstream, nobody has seen it yet.",
     "Upstream, a gauge reader writes the level by hand. Downstream, nobody has seen it yet.", STORY),
    ("story", "s4", "In September 2024, the Kosi at Birpur ran higher than at any time since 1968.",
     "In September twenty twenty four, the Kosi at Birpur ran higher than at any time since nineteen sixty eight.", STORY),
    ("story", "s5", "The water always takes hours. The warning should not.",
     "The water always takes hours. The warning should not.", STORY),
    ("turn", "t1", "This is NadiSaathi. A camera reads the river. An agent decides. A person approves.",
     "This is Nadi Saathi. A camera reads the river. An agent decides. A person approves.", PRODUCT),
    # --- the field hardware (private cut only, concept illustration)
    ("hardware", "h1", "In the field, a solar-powered camera on a pole watches a painted river gauge.",
     "In the field, a solar powered camera on a pole watches a painted river gauge.", PRODUCT),
    ("hardware", "h2", "Every five minutes, it sends a burst of frames over the mobile network to AWS.",
     "Every five minutes, it sends a burst of frames over the mobile network to A W S.", PRODUCT),
    ("hardware", "h3", "There, OpenCV finds the waterline and turns it into metres, and the agent decides what to do next.",
     "There, Open C V finds the waterline and turns it into metres, and the agent decides what to do next.", PRODUCT),
    ("hardware", "h4", "OpenCV already runs on small camera boards like these, so the camera can check its own frames at the river.",
     "Open C V already runs on small camera boards like these, so the camera can check its own frames at the river.", PRODUCT),
    # --- the live product
    ("live", "l1", "This is a replay of one flood night at Chatara, in Nepal.",
     "This is a replay of one flood night at Chatara, in Nepal.", PRODUCT),
    ("live", "l2", "Every five minutes, OpenCV turns a burst of frames into a level in metres, with an error bar.",
     "Every five minutes, Open C V turns a burst of frames into a level in metres, with an error bar.", PRODUCT),
    ("live", "l3", "When the river climbs fast, the agent checks twice as often.",
     "When the river climbs fast, the agent checks twice as often.", PRODUCT),
    ("live", "l4", "And it works out when the water reaches each town downstream, across the border.",
     "And it works out when the water reaches each town downstream, across the border.", PRODUCT),
    # --- OpenCV, opened up (Vision Lab)
    ("vision", "v1", "Here is one reading, opened up.", "Here is one reading, opened up.", PRODUCT),
    ("vision", "v2", "First, sharpness, glare and contrast, each against a limit. A bad frame can never move an alert.",
     "First, sharpness, glare and contrast, each against a limit. A bad frame can never move an alert.", PRODUCT),
    ("vision", "v3", "ORB matches the frame to the calibration image, so the gauge marks still line up if the camera shakes.",
     "Orb matches the frame to the calibration image, so the gauge marks still line up if the camera shakes.", PRODUCT),
    ("vision", "v4", "OpenCV straightens the gauge into one strip, and takes the median of five frames to remove ripples.",
     "Open C V straightens the gauge into one strip, and takes the median of five frames to remove ripples.", PRODUCT),
    ("vision", "v5", "Three detectors read it: edges, optical flow and colour. Two of the three must agree.",
     "Three detectors read it: edges, optical flow and colour. Two of the three must agree.", PRODUCT),
    ("vision", "v6", f"The whole pipeline takes about {F['opencv_ms']} milliseconds on AWS Graviton, with KleidiCV inside OpenCV.",
     f"The whole pipeline takes about {say(F['opencv_ms'])} milliseconds on A W S Graviton, with Klydee C V inside Open C V.", PRODUCT),
    ("vision", "v7", f"On real USGS river cameras, it reads the gauge within {F['real_mae_cm']} centimetres on average.",
     f"On real U S G S river cameras, it reads the gauge within {say(F['real_mae_cm'])} centimetres on average.", PRODUCT),
    # --- the agent, the model and the guard
    ("agent", "a1", "When its own detectors disagree, the agent asks Claude for a second opinion.",
     "When its own detectors disagree, the agent asks Claude for a second opinion.", PRODUCT),
    ("agent", "a2", "But a model can be wrong, or tricked. This reply tells the agent to switch the siren off.",
     "But a model can be wrong, or tricked. This reply tells the agent to switch the siren off.", PRODUCT),
    ("agent", "a3", f"The guard keeps the OpenCV reading and asks a person. It caught {F['guard_caught']} of {F['guard_bad']} bad replies.",
     f"The guard keeps the Open C V reading and asks a person. It caught {say(F['guard_caught'])} of {say(F['guard_bad'])} bad replies.", PRODUCT),
    ("approve", "p1", "In Supaul, the district control room reads the evidence, checks the Hindi alert, and approves it with a PIN.",
     "In Supaul, the district control room reads the evidence, checks the Hindi alert, and approves it with a pin.", PRODUCT),
    # --- under the hood (3D architecture)
    ("arch", "x1", "Under the hood, every reading climbs through six layers.",
     "Under the hood, every reading climbs through six layers.", PRODUCT),
    ("arch", "x2", "A camera sends five frames. OpenCV on Graviton turns them into metres, with an error bar.",
     "A camera sends five frames. Open C V on Graviton turns them into metres, with an error bar.", PRODUCT),
    ("arch", "x3", "The agent picks the next step. The guard checks every tool call and every model reply.",
     "The agent picks the next step. The guard checks every tool call and every model reply.", PRODUCT),
    ("arch", "x4", "A lying reply stops here. Only a person, with a PIN, lets an alert out to the districts.",
     "A lying reply stops here. Only a person, with a pin, lets an alert out to the districts.", PRODUCT),
    ("arch", "x5", "And every step is written to CloudWatch and S3 as it happens.",
     "And every step is written to CloudWatch and S three as it happens.", PRODUCT),
    # --- AWS, the proof
    ("aws", "w1", "Every cycle becomes a JSON event in CloudWatch Logs, and an evidence file in S3.",
     "Every cycle becomes a jason event in CloudWatch Logs, and an evidence file in S three.", PRODUCT),
    ("aws", "w2", "Logs Insights reads the timing of every OpenCV stage, straight from production.",
     "Logs Insights reads the timing of every Open C V stage, straight from production.", PRODUCT),
    ("aws", "w3", f"One CloudFormation stack, {F['stack_resources']} resources, on a single Graviton instance.",
     f"One CloudFormation stack, {say(F['stack_resources'])} resources, on a single Graviton instance.", PRODUCT),
    ("aws", "w5", "If an alert waits too long, Step Functions reminds the operators, up to three times.",
     "If an alert waits too long, Step Functions reminds the operators, up to three times.", PRODUCT),
    ("built", "b1", "Built with OpenCV 5 on AWS Graviton, with CloudWatch, S3, Step Functions, Polly, SNS and Claude.",
     "Built with Open C V five on A W S Graviton, with CloudWatch, S three, Step Functions, Polly, S N S and Claude.", PRODUCT),
    ("aws", "w4", "Other agents can use it through MCP. None of its tools can approve an alert.",
     "Other agents can use it through M C P. None of its tools can approve an alert.", PRODUCT),
    # --- proof in numbers
    ("proof", "n1", f"In {F['suite_success'].split('/')[1]} replays, the first alert came a median {F['lead_min']} minutes before the river crossed the warning level.",
     f"In {say(F['suite_success'].split('/')[1])} replays, the first alert came a median {say(F['lead_min'])} minutes before the river crossed the warning level.", PRODUCT),
    # --- close
    ("close", "c1", "NadiSaathi. The river friend.", "Nadi Saathi. The river friend.", STORY),
]


def load():
    for scene, lid, caption, spoken, (ex, cfg) in LINES:
        yield scene, lid, caption, spoken, ex, cfg


if __name__ == "__main__":
    total = 0
    for scene, lid, caption, spoken, ex, cfg in load():
        n = len(spoken.split())
        total += n
        print(f"{lid:3s} {n:3d}w  {caption}")
    print("words:", total)
