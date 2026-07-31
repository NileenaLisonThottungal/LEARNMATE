import string

import numpy as np
import pke
from flashtext import KeywordProcessor
from nltk.corpus import stopwords, wordnet
from nltk.tokenize import sent_tokenize, word_tokenize
from sklearn.feature_extraction.text import TfidfVectorizer
from summarizer import Summarizer
from transformers import T5ForConditionalGeneration, T5Tokenizer

_tokenizer = None
_model = None


def _load_model():
    """Lazily load the T5 model on first use so importing this module stays cheap."""
    global _tokenizer, _model
    if _tokenizer is None:
        _tokenizer = T5Tokenizer.from_pretrained("google/flan-t5-base")
        _model = T5ForConditionalGeneration.from_pretrained("google/flan-t5-base")
    return _tokenizer, _model


def summarize_text(text: str) -> str:
    model = Summarizer(model="distilbert-base-uncased")
    result = model(text, min_length=60, max_length=500, ratio=0.4)
    return "".join(result)


def get_nouns_multipartite(text: str) -> list[str]:
    extractor = pke.unsupervised.MultipartiteRank()
    stoplist = list(string.punctuation) + stopwords.words("english")
    extractor.load_document(input=text, stoplist=stoplist)
    pos = {"PROPN", "NOUN"}
    extractor.candidate_selection(pos=pos)
    extractor.candidate_weighting(alpha=1.1, threshold=0.75, method="average")
    keyphrases = extractor.get_n_best(n=20)
    return [key[0] for key in keyphrases]


def extract_keywords_tfidf(text: str, top_n: int = 5) -> list[str]:
    vectorizer = TfidfVectorizer(stop_words="english")
    tfidf_matrix = vectorizer.fit_transform([text])
    feature_array = np.array(vectorizer.get_feature_names_out())
    tfidf_sorting = np.argsort(tfidf_matrix.toarray()).flatten()[::-1]
    return feature_array[tfidf_sorting][:top_n].tolist()


def tokenize_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in sent_tokenize(text) if len(sentence) > 20]


def get_sentences_for_keyword(keywords: list[str], sentences: list[str]) -> dict[str, list[str]]:
    keyword_processor = KeywordProcessor()
    keyword_sentences = {word: [] for word in keywords}
    for word in keywords:
        keyword_processor.add_keyword(word)
    for sentence in sentences:
        keywords_found = keyword_processor.extract_keywords(sentence)
        for key in keywords_found:
            keyword_sentences[key].append(sentence)
    return {key: val for key, val in keyword_sentences.items() if len(val) >= 2}


def generate_question(sentences: str, keyword: str) -> str:
    tokenizer, model = _load_model()
    prompt = f"Generate a detailed question focusing on the keyword '{keyword}' based on these sentences: {sentences}"
    input_ids = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512).input_ids
    outputs = model.generate(input_ids, max_length=120, temperature=0.7, top_p=0.9, do_sample=True)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


def generate_hint(sentence: str) -> str:
    tokenizer, model = _load_model()
    prompt = f"Generate a meaningful question based on this sentence to guide understanding: {sentence}"
    input_ids = tokenizer(prompt, return_tensors="pt", truncation=True, max_length=512).input_ids
    outputs = model.generate(input_ids, max_length=80, temperature=0.7, top_p=0.9, do_sample=True)
    return tokenizer.decode(outputs[0], skip_special_tokens=True)


def extract_keywords_per_sentence(sentence: str) -> list[str]:
    words = word_tokenize(sentence)
    return list({word for word in words if wordnet.synsets(word)})


def generate_qa_from_text(text: str) -> dict:
    """
    Pure function: raw document text -> quiz data.

    Returns {section_key: {question, hint1..N, sentence1..N, answer_key}},
    the same shape the static JSON datasets and backend/database.py's
    insert_questions() expect.
    """
    summarized_text = summarize_text(text)

    keywords_multipartite = get_nouns_multipartite(text)
    keywords_tfidf = extract_keywords_tfidf(text)
    keywords = list(set(keywords_multipartite + keywords_tfidf))

    sentences = tokenize_sentences(summarized_text)
    keyword_sentence_mapping = get_sentences_for_keyword(keywords, sentences)

    qa_data = {}
    section_num = 1
    for keyword, kw_sentences in keyword_sentence_mapping.items():
        selected_sentences = kw_sentences[:5]
        question = generate_question(" ".join(selected_sentences), keyword)
        if not question:
            continue

        entry = {"question": question}
        for i, sentence in enumerate(selected_sentences, start=1):
            entry[f"hint{i}"] = generate_hint(sentence)
            entry[f"sentence{i}"] = sentence
        entry["answer_key"] = " ".join(selected_sentences).strip()

        qa_data[f"{section_num}. {keyword.upper()}"] = entry
        section_num += 1

    return qa_data
