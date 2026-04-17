"""Systematic EN seed-prompt enumerator for the static phrasebook API.

Goal: generate a broad-but-curated set of high-utility English prompts whose
Slovenian translations will be exposed as a GitHub-Pages static API. The set
covers the linguistic surface that a traveller/learner actually produces:

  * greetings, thanks, apologies, goodbye (social glue)
  * questions (wh-, yes/no, polite requests)
  * food & restaurant ordering (incl. quantities, allergies)
  * transport & wayfinding (stations, tickets, directions)
  * accommodation (check-in/out, rooms)
  * emergency & health (pharmacy, doctor, police)
  * money & numbers (1-20, prices)
  * time & dates (hours, days, common relative times)
  * small talk (yes/no, agreement, disagreement)
  * common verbs in 1sg present (I want, I need, I have, etc.)

The enumerator is deliberately written out long-hand rather than template-
expanded, because Slovenian agreement (gender/case/number) makes template
expansion sensitive to slot co-occurrence — a template would produce
grammatically wrong outputs even if tokens are individually valid.

Invoked by ``build.api.build_phrasebook`` — you should not need to run it
directly.
"""
from __future__ import annotations


# Each category is a list of (en, category, register) tuples.
def _prompts() -> list[tuple[str, str, str]]:
    # Format: (english, category, register)
    out: list[tuple[str, str, str]] = []

    # --- Greetings & politeness (formal + informal) ----------------------
    for e in [
        "Good morning.",
        "Good afternoon.",
        "Good evening.",
        "Good night.",
        "Hello.",
        "Hi.",
        "Goodbye.",
        "See you later.",
        "See you tomorrow.",
        "Nice to meet you.",
        "How are you?",
        "I am fine, thank you.",
        "Thank you.",
        "Thank you very much.",
        "You are welcome.",
        "Please.",
        "Excuse me.",
        "I am sorry.",
        "No problem.",
        "Yes.",
        "No.",
        "Maybe.",
        "Of course.",
        "I do not understand.",
        "Could you repeat that, please?",
        "Could you speak more slowly, please?",
        "Do you speak English?",
        "Do you speak German?",
        "I speak a little Slovenian.",
        "My name is Anna.",
        "What is your name?",
    ]:
        out.append((e, "greetings", "formal"))

    # --- Questions frame ------------------------------------------------
    for e in [
        "Where is the train station?",
        "Where is the bus station?",
        "Where is the airport?",
        "Where is the hotel?",
        "Where is the restaurant?",
        "Where is the pharmacy?",
        "Where is the nearest pharmacy?",
        "Where is the hospital?",
        "Where is the police station?",
        "Where is the bathroom?",
        "Where is the exit?",
        "Where is the entrance?",
        "Where is the market?",
        "Where is the city center?",
        "Where is the embassy?",
        "How much does this cost?",
        "How much is a ticket?",
        "How much for a coffee?",
        "How far is it?",
        "How long does it take?",
        "When does the train leave?",
        "When does the bus arrive?",
        "When does the shop open?",
        "When does the shop close?",
        "What time is it?",
        "What is this?",
        "What is that?",
        "Why is it closed?",
        "Can you help me?",
        "Can I pay by card?",
        "Can I pay in cash?",
        "Do you have a menu in English?",
        "Do you have wifi?",
        "Is this seat taken?",
        "Is breakfast included?",
        "Is it far from here?",
    ]:
        out.append((e, "questions", "formal"))

    # --- Food & restaurant ---------------------------------------------
    for e in [
        "A table for two, please.",
        "The menu, please.",
        "I would like a coffee.",
        "I would like a tea.",
        "I would like a beer.",
        "I would like a glass of water.",
        "I would like a glass of wine.",
        "I would like the soup.",
        "I would like a salad.",
        "I would like the fish.",
        "I would like a vegetarian dish.",
        "Without meat, please.",
        "Without gluten, please.",
        "I am allergic to nuts.",
        "I am allergic to lactose.",
        "The food was delicious.",
        "The bill, please.",
        "Cheers!",
        "Can I have the receipt, please?",
        "One more, please.",
        "Two coffees, please.",
        "Is this dish spicy?",
        "What do you recommend?",
    ]:
        out.append((e, "food", "formal"))

    # --- Transport -----------------------------------------------------
    for e in [
        "Two tickets to Ljubljana, please.",
        "One ticket to Maribor, please.",
        "A return ticket, please.",
        "A one-way ticket, please.",
        "Which platform?",
        "Is this the train to Ljubljana?",
        "Is this the bus to Bled?",
        "Where can I find a taxi?",
        "Please take me to the airport.",
        "Please take me to this address.",
        "How much is the fare?",
        "Stop here, please.",
        "I would like to rent a car.",
        "I am going to Koper.",
        "I am going to Maribor.",
        "When is the next train?",
        "When is the next bus?",
        "Does this bus stop at the center?",
        "I missed my train.",
        "I lost my ticket.",
    ]:
        out.append((e, "transport", "formal"))

    # --- Accommodation -------------------------------------------------
    for e in [
        "I have a reservation.",
        "I would like a single room.",
        "I would like a double room.",
        "How much is the room per night?",
        "Is breakfast included?",
        "What time is breakfast?",
        "What time is check-out?",
        "Can I have the wifi password?",
        "The room is too cold.",
        "The room is too warm.",
        "The shower is broken.",
        "I would like to check out.",
    ]:
        out.append((e, "accommodation", "formal"))

    # --- Emergency & health -------------------------------------------
    for e in [
        "Help!",
        "Call the police!",
        "Call an ambulance!",
        "I need a doctor.",
        "I am sick.",
        "I have a headache.",
        "I have a fever.",
        "It hurts here.",
        "I have lost my passport.",
        "I have been robbed.",
        "Where is the nearest hospital?",
        "Is there a pharmacy open now?",
        "I need medicine for a cold.",
    ]:
        out.append((e, "emergency", "formal"))

    # --- Numbers, money, time -----------------------------------------
    for e in [
        "One.", "Two.", "Three.", "Four.", "Five.",
        "Six.", "Seven.", "Eight.", "Nine.", "Ten.",
        "Twenty.", "Fifty.", "One hundred.",
        "Five euros.",
        "Twenty euros.",
        "It is three o'clock.",
        "It is half past five.",
        "It is Monday.",
        "It is Tuesday.",
        "It is Wednesday.",
        "It is Thursday.",
        "It is Friday.",
        "It is Saturday.",
        "It is Sunday.",
        "Today.",
        "Tomorrow.",
        "Yesterday.",
        "This morning.",
        "This evening.",
        "Right now.",
    ]:
        out.append((e, "numbers_time", "formal"))

    # --- Directions ----------------------------------------------------
    for e in [
        "Turn left.",
        "Turn right.",
        "Go straight.",
        "Stop.",
        "It is on the left.",
        "It is on the right.",
        "Next to the bank.",
        "In front of the church.",
        "Behind the hotel.",
        "Near the square.",
        "Across the street.",
    ]:
        out.append((e, "directions", "formal"))

    # --- Weather & small talk -----------------------------------------
    for e in [
        "It is hot today.",
        "It is cold today.",
        "It is raining.",
        "It is snowing.",
        "It is sunny.",
        "Slovenia is beautiful.",
        "I like Slovenian food.",
        "I am from Germany.",
        "I am a tourist.",
        "I am here on holiday.",
        "I am here for business.",
        "Have a nice day.",
    ]:
        out.append((e, "smalltalk", "formal"))

    # --- Common first-person verbs (useful scaffolds) -----------------
    for e in [
        "I want water.",
        "I need help.",
        "I have a question.",
        "I do not know.",
        "I think so.",
        "I agree.",
        "I do not agree.",
        "I am hungry.",
        "I am thirsty.",
        "I am tired.",
        "I am lost.",
        "I understand.",
        "I am waiting.",
        "I am looking for the station.",
        "I am looking for a hotel.",
        "I am looking for a pharmacy.",
        "I live in Germany.",
        "I work in Berlin.",
        "I study Slovenian.",
        "I am learning Slovenian.",
        "I am a student.",
        "I am a teacher.",
        "I am an engineer.",
    ]:
        out.append((e, "common_verbs", "formal"))

    # --- Shopping & services ------------------------------------------
    for e in [
        "Do you accept credit cards?",
        "Do you have a smaller size?",
        "Do you have a larger size?",
        "Do you have another color?",
        "I am just looking, thank you.",
        "I would like to try this on.",
        "Where is the fitting room?",
        "How much is this?",
        "It is too expensive.",
        "Do you have a discount?",
        "Can you give me a receipt?",
        "I would like to exchange this.",
        "I would like a refund.",
        "Is this on sale?",
        "Open.",
        "Closed.",
        "Entrance.",
        "Exit.",
        "Push.",
        "Pull.",
        "Private.",
        "No smoking.",
    ]:
        out.append((e, "shopping", "formal"))

    # --- People, family, introductions --------------------------------
    for e in [
        "This is my friend.",
        "This is my wife.",
        "This is my husband.",
        "This is my mother.",
        "This is my father.",
        "This is my brother.",
        "This is my sister.",
        "I have two children.",
        "I am married.",
        "I am single.",
        "How old are you?",
        "I am twenty-five years old.",
        "Where are you from?",
        "I am from Germany.",
        "I am from Austria.",
        "I am from Switzerland.",
        "Where do you live?",
        "I live in Munich.",
    ]:
        out.append((e, "introductions", "formal"))

    # --- Weather extended ---------------------------------------------
    for e in [
        "It is windy.",
        "It is foggy.",
        "It is cloudy.",
        "The sky is clear.",
        "It is a beautiful day.",
        "It is freezing.",
        "The weather is nice.",
        "The weather is bad.",
        "Will it rain tomorrow?",
        "What is the temperature?",
        "It is twenty degrees.",
        "It is below zero.",
    ]:
        out.append((e, "weather", "formal"))

    # --- Requests & politeness layer ----------------------------------
    for e in [
        "Could you help me, please?",
        "Could you tell me the way?",
        "Could you show me on the map?",
        "Could you write it down, please?",
        "Could you wait a moment?",
        "May I come in?",
        "May I sit here?",
        "May I ask you something?",
        "Would you like some water?",
        "Would you like to join us?",
        "Please hurry.",
        "Please be careful.",
        "Please wait here.",
        "One moment, please.",
        "Come in, please.",
        "Have a seat, please.",
    ]:
        out.append((e, "requests", "formal"))

    # --- Telephone & messaging ----------------------------------------
    for e in [
        "May I speak to the manager?",
        "Is this the right number?",
        "Could you call me back?",
        "I will call you later.",
        "I cannot hear you well.",
        "The line is bad.",
        "Please leave a message.",
        "My phone number is …",
        "Can you send me a message?",
        "I will send you an email.",
    ]:
        out.append((e, "phone", "formal"))

    # --- Airport & border control -------------------------------------
    for e in [
        "I am here on vacation.",
        "I am here for business.",
        "I will stay for one week.",
        "I will stay for five days.",
        "I have nothing to declare.",
        "Here is my passport.",
        "Here is my visa.",
        "Where is the baggage claim?",
        "My luggage is missing.",
        "Where is the customs?",
        "Where is gate twelve?",
        "When is boarding?",
        "The flight is delayed.",
        "The flight is cancelled.",
    ]:
        out.append((e, "airport", "formal"))

    # --- Restaurant extended ------------------------------------------
    for e in [
        "I have a reservation for two.",
        "We would like a table by the window.",
        "We would like to sit outside.",
        "Could we see the wine list?",
        "What is the dish of the day?",
        "What soups do you have?",
        "I will have the steak, medium.",
        "Rare, please.",
        "Well done, please.",
        "No ice, please.",
        "With ice, please.",
        "Still water, please.",
        "Sparkling water, please.",
        "Black coffee, please.",
        "Coffee with milk, please.",
        "A small beer, please.",
        "A large beer, please.",
        "Another glass of wine, please.",
        "Could we order, please?",
        "Could we pay separately?",
        "Could we pay together?",
        "Keep the change.",
        "The food is very good.",
        "The food is cold.",
        "This is not what I ordered.",
    ]:
        out.append((e, "restaurant", "formal"))

    # --- Money, banking, ATM ------------------------------------------
    for e in [
        "Where is the nearest ATM?",
        "Where can I change money?",
        "What is the exchange rate?",
        "I would like to withdraw money.",
        "My card does not work.",
        "The machine swallowed my card.",
        "Do you have change?",
        "In small bills, please.",
        "In large bills, please.",
        "Only cash, no card.",
    ]:
        out.append((e, "money", "formal"))

    # --- Taxi & ride-hailing ------------------------------------------
    for e in [
        "Could you call a taxi, please?",
        "How long will the taxi take?",
        "Please drive to the airport.",
        "Please drive to the hotel.",
        "Please drive faster.",
        "Please drive more slowly.",
        "Please turn left here.",
        "Please turn right here.",
        "Please stop at the next corner.",
        "Please wait here for five minutes.",
        "I am in a hurry.",
    ]:
        out.append((e, "taxi", "formal"))

    # --- Health & symptoms extended -----------------------------------
    for e in [
        "I have a cough.",
        "I have a sore throat.",
        "I have a stomachache.",
        "I have a toothache.",
        "I feel dizzy.",
        "I feel nauseous.",
        "I am pregnant.",
        "I am diabetic.",
        "I have high blood pressure.",
        "I take this medication.",
        "I am allergic to penicillin.",
        "Is there a dentist nearby?",
        "I need an X-ray.",
        "I have had an accident.",
    ]:
        out.append((e, "health", "formal"))

    # --- Signs, warnings, notices -------------------------------------
    for e in [
        "Danger.",
        "Caution.",
        "Wet floor.",
        "Do not enter.",
        "Out of order.",
        "No parking.",
        "No photography.",
        "Keep off the grass.",
        "Mind the step.",
        "Emergency exit.",
        "Lost and found.",
        "Reserved.",
        "Free.",
        "Occupied.",
    ]:
        out.append((e, "signs", "formal"))

    # --- Internet & tech small talk -----------------------------------
    for e in [
        "What is the wifi password?",
        "Is the wifi free?",
        "My battery is dead.",
        "Do you have a charger?",
        "Is there an outlet here?",
        "My phone is not working.",
        "How do I connect to the wifi?",
    ]:
        out.append((e, "tech", "formal"))

    # --- Opinions & feelings ------------------------------------------
    for e in [
        "I like it.",
        "I do not like it.",
        "It is wonderful.",
        "It is terrible.",
        "It is interesting.",
        "It is boring.",
        "It is too much.",
        "It is not enough.",
        "That is fine.",
        "That is perfect.",
        "I am happy.",
        "I am sad.",
        "I am worried.",
        "I am surprised.",
        "Do not worry.",
        "It is not important.",
    ]:
        out.append((e, "feelings", "formal"))

    # --- Time, dates, seasons extended --------------------------------
    for e in [
        "What day is it today?",
        "What is the date today?",
        "In January.",
        "In February.",
        "In March.",
        "In April.",
        "In May.",
        "In June.",
        "In July.",
        "In August.",
        "In September.",
        "In October.",
        "In November.",
        "In December.",
        "In spring.",
        "In summer.",
        "In autumn.",
        "In winter.",
        "Last week.",
        "Next week.",
        "Last month.",
        "Next month.",
        "In ten minutes.",
        "In an hour.",
        "In two hours.",
        "Just a moment.",
    ]:
        out.append((e, "time_dates", "formal"))

    # --- Transport extended -------------------------------------------
    for e in [
        "Where can I buy a ticket?",
        "Can I buy a ticket on the bus?",
        "Can I buy a ticket on the train?",
        "Where is the ticket machine?",
        "Is there a night train?",
        "Is there a direct bus?",
        "Do I need to change trains?",
        "Where do I change?",
        "Is this the express?",
        "Is this a direct flight?",
        "Which exit do I need?",
        "Can you tell me when to get off?",
        "I need to get off at the next stop.",
    ]:
        out.append((e, "transport_extended", "formal"))

    # --- Touristy things ----------------------------------------------
    for e in [
        "What do you recommend to see?",
        "Are there any tours?",
        "Is there an audio guide?",
        "Can I take photos?",
        "When does it open?",
        "When does it close?",
        "How much is the entrance?",
        "Is there a student discount?",
        "Is there a group discount?",
        "Where is the information desk?",
        "Do you have a map of the city?",
        "I would like a guided tour.",
        "Can we take a photo together?",
    ]:
        out.append((e, "tourism", "formal"))

    # --- Numbers extended ---------------------------------------------
    for e in [
        "Eleven.", "Twelve.", "Thirteen.", "Fourteen.", "Fifteen.",
        "Sixteen.", "Seventeen.", "Eighteen.", "Nineteen.",
        "Thirty.", "Forty.", "Sixty.", "Seventy.", "Eighty.", "Ninety.",
        "Two hundred.", "Five hundred.", "One thousand.",
        "First.", "Second.", "Third.", "Fourth.", "Fifth.",
        "One euro.", "Two euros.", "Ten euros.", "Fifty euros.", "One hundred euros.",
    ]:
        out.append((e, "numbers_extended", "formal"))

    return out


def generate() -> list[dict]:
    return [
        {"en": e, "category": c, "register": r}
        for (e, c, r) in _prompts()
    ]


def main() -> int:
    import json
    import sys

    items = generate()
    print(f"[seed] {len(items)} prompts", file=sys.stderr)
    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
