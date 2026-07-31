import json
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Load JSON file
with open("updated_final_t5_bert_hint_qa.json", "r", encoding="utf-8", errors="ignore") as file:
    json_data = json.load(file)


# Function to compute similarity using cosine similarity
def compute_similarity(user_answer, correct_answer):
    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform([user_answer, correct_answer])
    similarity = cosine_similarity(vectors[0], vectors[1])[0][0]
    return round(similarity * 100, 2)  # Convert to percentage

# Iterate through sections in JSON
for section, content in json_data.items():
    question = content.get("question", "No question provided")
    
    hints = [content.get(f"hint{i}") for i in range(1, 6) if content.get(f"hint{i}")]
    sentences = [content.get(f"sentence{i}", "") for i in range(1, 6)]
    answer_key = content.get("answer_key", "No answer key provided")  # Fetch answer key
    
    correct_answer = " ".join(sentences).strip()  # Full correct answer
    hints_output = "\n".join([f"- {hint}" for hint in hints]) if hints else None

    print(f"\nQuestion: {question}")

    while True:
        user_input = input("Enter your answer: ").strip()  # Get user answer

        if not user_input:
            print("⚠️ Please enter a valid answer.")
            continue  # Prompt again if input is empty

        similarity_score = compute_similarity(user_input, correct_answer)

        if similarity_score >= 90:
            print("✅ You are correct!")
            break  # Move to next question
        elif similarity_score >= 50:
            print("🤔 Not quite right, try again!")
            if hints_output:
                print(f"Here are some hints:\n{hints_output}")
                print(f"\n📌 The correct answer is: {answer_key}")  # Show correct answer
        else:
            print("❌ Incorrect.")
            if hints_output:
                print(f"Here are some hints:\n{hints_output}")
            print(f"\n📌 The correct answer is: {answer_key}")  # Show correct answer
            break  # Move to next question

print("\nAll questions have been answered!")
