/**
 * Story page content. Every factual claim lives here as data.
 *
 * Real-world figures (deaths, people affected, discharge, travel times) are NOT
 * written into the text. They are `{ placeholder: 'FACT:<key>' }` objects that
 * render as a "[source pending]" chip until the lead engineer replaces them with
 * a verified value and its source, e.g.
 *   { value: '…', source: 'Agency report, year', url: '…' }
 *
 * The flood night itself is a scenario: the places and the river are real,
 * the night and the people are illustrative.
 */

export interface FactPlaceholder {
  placeholder: `FACT:${string}`;
}

export interface VerifiedFact {
  value: string;
  source: string;
  url?: string;
}

export type StoryPart = string | FactPlaceholder | VerifiedFact;
export type RichText = StoryPart[];

export interface StoryChapter {
  id: string;
  time: string;
  place: string;
  country: 'NP' | 'IN';
  heading: string;
  body: RichText[];
  /** Name of the illustrative persona featured in this chapter, if any. */
  persona?: string;
}

export function isPlaceholder(part: StoryPart): part is FactPlaceholder {
  return typeof part === 'object' && part !== null && 'placeholder' in part;
}

export function isVerified(part: StoryPart): part is VerifiedFact {
  return typeof part === 'object' && part !== null && 'value' in part;
}

export const storyMeta = {
  title: 'The river rose at night. The warning arrived first.',
  lede: [
    'The Koshi rises in the hills of Nepal and flows into the plains of Bihar, India. ',
    'When it floods, the water reaches villages downstream hours after it is first seen upstream. ',
    'NadiSaathi is built to use those hours.',
  ] as RichText,
  scenarioNote:
    'This is a scenario told as a story. The river and the places are real; the flood night is a replay of synthetic camera frames measured by the same OpenCV pipeline the system runs.',
  personaNote:
    'Sita and Rakesh are illustrative composites based on the roles of a ward disaster focal person in Nepal and a District Disaster Management Authority (DDMA) control-room operator in India. They are not real people.',
};

export const context: { heading: string; body: RichText[] } = {
  heading: 'Why this matters',
  body: [
    [
      'On 18 August 2008 the Koshi broke through its eastern embankment near Kusaha in Nepal. ',
      {
        value: 'The breach hit Sunsari and Saptari in Nepal and six districts of Bihar.',
        source: 'Water Resources Department, Bihar (FMIS)',
        url: 'https://fmiscwrdbihar.gov.in/fmis/history.html',
      },
    ],
    [
      'It is not history. ',
      {
        value: 'On 29 September 2024 the Kosi at the Birpur barrage peaked at 661,295 cusecs, the highest flow since 1968.',
        source: 'Government of Bihar flood report, 2024',
        url: 'https://betastate.bihar.gov.in/file_2/FileUpload/2025/Jan/26-Jan-2025/43/DyPage/49e49e10-696c-41ae-8e4e-37dc9d5902d7.pdf',
      },
      ' In the same storm, ',
      {
        value: "Nepal's Home Ministry counted 209 dead and 29 missing.",
        source: 'Nepal Home Ministry via All India Radio News (secondary)',
        url: 'https://www.newsonair.gov.in/nepal-flood-death-toll-rises-to-209-over-4500-rescued',
      },
    ],
    [
      'Bihar carries a large share of India’s flood risk: ',
      {
        value: "its flood-affected area is about 17.2% of India's flood-prone area.",
        source: 'Government of Bihar',
        url: 'https://stc.bihar.gov.in/ShowDepartmentContentSubT.aspx?Id=MTI%3D',
      },
      ' And the water comes from upstream. ',
      {
        value: "Bihar's own flood forecasts in October 2026 noted that observed rainfall and water-level data from Nepal were unavailable to them.",
        source: 'WRD Bihar, Kosi forecast bulletin',
        url: 'https://www.fmiscwrdbihar.gov.in/bulletin/Kosi_Model_Result.pdf',
      },
    ],
    [
      'Chatara, where the Koshi leaves the hills, is ',
      {
        value: 'about 43 km from the Kosi barrage',
        source: 'ISPRS Archives XL-8, 2014 (secondary)',
        url: 'https://isprs-archives.copernicus.org/articles/XL-8/1345/2014/isprsarchives-XL-8-1345-2014.pdf',
      },
      '. NadiSaathi’s river graph turns that distance into an arrival window of a few hours for Birpur, labelled as an estimate, and measures on real river gauges how much earlier an upstream warning arrives.',
    ],
  ],
};

export const chapters: StoryChapter[] = [
  {
    id: 'upstream',
    time: 'Evening',
    place: 'Chatara, Sunsari',
    country: 'NP',
    heading: 'A camera watches the river',
    body: [
      [
        'It has rained in the hills for two days. In this scenario a fixed camera looks at a gauge on the bank at Chatara. ',
        'Every cycle, OpenCV finds the waterline in the frame and turns it into a river stage in metres, with an error bar, using three independent estimators.',
      ],
      [
        'If the picture is too dark, blurred or shifted, the reading is marked unusable instead of guessed. The agent never acts on a number it cannot trust.',
      ],
    ],
  },
  {
    id: 'rise',
    time: 'Late evening',
    place: 'Chatara, Sunsari',
    country: 'NP',
    heading: 'The river starts to rise fast',
    body: [
      [
        'The measured rise rate crosses the agent’s threshold. It starts checking the camera far more often, and asks the question that matters downstream: when will this water arrive?',
      ],
      [
        'When the three estimators disagree, and only then, it asks a larger vision model for a second opinion. If that model contradicts the measurement, the measurement is kept and a person is asked to look.',
      ],
    ],
  },
  {
    id: 'eta',
    time: 'Same hour',
    place: 'Koshi Barrage to Supaul',
    country: 'IN',
    heading: 'Hours of warning, not minutes',
    body: [
      [
        'Using travel times along the river graph, the agent estimates an arrival window for the Koshi Barrage and the embankment villages in Bihar, as a range rather than a single promise.',
      ],
      [
        'It drafts short warnings in Nepali, Hindi and Maithili, sized to fit an SMS, with a voice version for people who do not read. Each draft carries the evidence that led to it. Nothing is sent yet.',
      ],
    ],
  },
  {
    id: 'sita',
    time: 'Night',
    place: 'Saptari',
    country: 'NP',
    persona: 'Sita',
    heading: 'Sita reviews the Nepali message',
    body: [
      [
        'Sita is the ward disaster focal person. On her phone she sees the camera frame, the measured level and why the agent thinks it matters.',
      ],
      [
        'She changes one line so it sounds like her, enters her PIN and approves it. The message goes out to her ward in her name, not the machine’s.',
      ],
    ],
  },
  {
    id: 'rakesh',
    time: 'Night',
    place: 'DDMA control room, Supaul',
    country: 'IN',
    persona: 'Rakesh',
    heading: 'Rakesh approves across the border',
    body: [
      [
        'In the district control room, Rakesh sees the same evidence and the same arrival window. He approves the Hindi and Maithili SMS, the voice call and the CAP alert for the embankment villages.',
      ],
      ['Every approval is logged with who decided, when, and what they changed.'],
    ],
  },
  {
    id: 'move',
    time: 'Before the water',
    place: 'Embankment villages, Supaul',
    country: 'IN',
    heading: 'Families move while the road is dry',
    body: [
      [
        'Phones buzz. A recorded voice repeats the warning in Maithili. Families gather documents, medicines and the elderly, untie the animals, and walk to the school shelter while the road is still above water.',
      ],
    ],
  },
  {
    id: 'after',
    time: 'Morning after',
    place: 'Supaul and Saptari',
    country: 'IN',
    heading: 'Relief, checked by people',
    body: [
      [
        'Volunteers log needs in their own language: a boat for a family on a roof, medicine for a clinic. Duplicates are flagged so one call does not become three.',
      ],
      [
        'A volunteer sends a photo of a flooded culvert. The system estimates the water depth with an error bar and marks the road as likely blocked, and a person confirms before the route board changes.',
      ],
    ],
  },
];

export const principles: string[] = [
  'A person approves every public alert, every dispatch and every route change.',
  'Every number links back to the camera frame and the step that produced it.',
  'The larger model is called only when the measurements disagree, and it cannot overrule them on its own.',
  'Warnings are short, local and spoken: Nepali, Hindi and Maithili, by SMS, voice and CAP.',
];
