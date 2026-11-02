import gzip
import json
import numpy as np
import pandas as pd
from sklearn.multiclass import OneVsRestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, mean_squared_error, f1_score
from sklearn.feature_extraction.text import TfidfVectorizer
from collections import Counter
import time

ATTRIBUTES = [
    "gender", "age", "education", "household_income", "industry",
    "employment_status", "employer_size", "home_ownership", "parental_status",
]

def extract_queries(searches):
    if isinstance(searches, list):
        return " ".join([item.get("query", "") for item in searches])
    return ""

from collections import Counter

# print("start...")
# start = time.time()

def build_lang_mapping(df, min_count=20):

    all_langs = []
    for langs in df["accept_languages"]:
        if isinstance(langs, list):
            all_langs.extend(langs)
    lang_counter = Counter(all_langs)
    common_langs = {lang for lang, cnt in lang_counter.items() if cnt >= min_count}
    lang_to_id = {lang: i for i, lang in enumerate(sorted(common_langs))}
    other_id = len(lang_to_id)
    return lang_to_id, other_id

def extract_extra_features(df, lang_to_id, other_id):

    df["first_seen_dt"] = pd.to_datetime(df["first_seen"], errors="coerce")
    df["last_seen_dt"] = pd.to_datetime(df["last_seen"], errors="coerce")
    df["years_active"] = (df["last_seen_dt"] - df["first_seen_dt"]).dt.days / 365.25
    df["years_active"] = df["years_active"].fillna(0)


    df["num_user_agents"] = df["user_agents"].apply(
        lambda x: len(x) if isinstance(x, list) else 0
    )

    def get_lang_cat(langs):
        if not isinstance(langs, list) or len(langs) == 0:
            return other_id
        primary = langs[0]
        return lang_to_id.get(primary, other_id)

    df["lang_cat"] = df["accept_languages"].apply(get_lang_cat)

    df["num_searches"] = df["searches"].apply(
        lambda x: len(x) if isinstance(x, list) else 0
    )

    feature_cols = ["years_active", "num_user_agents", "lang_cat", "num_searches"]
    return df[feature_cols].values

def data_prep():
    df_train = pd.read_json("train.jsonl.gz", lines=True, compression="gzip")
    df_dev = pd.read_json("dev.jsonl.gz", lines=True, compression="gzip")
    df_test =  pd.read_json("test.jsonl.gz", lines=True, compression="gzip")

    # print(f"Finish reading {time.time() - start:.1f}")
    # print(df_train.shape)
    # print(df_train.head())

    df_train_sorted = df_train.sort_values(by="client_id")
    df_dev_sorted = df_dev.sort_values(by="client_id")
    # print(df_train_sorted.head())

    df_train_label = pd.read_csv("train_labels.csv")
    df_train_label_sorted = df_train_label.sort_values(by="client_id")
    df_dev_label = pd.read_csv("dev_labels.csv")
    df_dev_label_sorted = df_dev_label.sort_values(by="client_id")
    # print(df_train_label_sorted.head())

    # df_train_base = pd.concat([df_train_sorted , df_train_label_sorted], ignore_index=True)
    # print(df_train_base.head())

    # Turn query into a single column
    df_train_sorted["query_text"] = df_train_sorted["searches"].apply(extract_queries)
    df_dev_sorted["query_text"] = df_dev_sorted["searches"].apply(extract_queries)
    df_test["query_text"] = df_test["searches"].apply(extract_queries)

    # Vectorize with  TF-IDF
    vectorizer = TfidfVectorizer(
        max_features=5000,     
        stop_words="english", 
        ngram_range=(1, 2)    
    )

    X_train = vectorizer.fit_transform(df_train_sorted["query_text"])
    X_dev = vectorizer.transform(df_dev_sorted["query_text"])
    X_test = vectorizer.transform(df_test["query_text"])

    lang_to_id, other_id = build_lang_mapping(df_train_sorted, min_count=20)
    X_train_extra = extract_extra_features(df_train_sorted, lang_to_id, other_id)
    X_dev_extra = extract_extra_features(df_dev_sorted, lang_to_id, other_id)
    X_test_extra = extract_extra_features(df_test, lang_to_id, other_id)

    X_train = np.hstack([X_train.toarray(), X_train_extra])
    X_dev = np.hstack([X_dev.toarray(), X_dev_extra])
    X_test = np.hstack([X_test.toarray(), X_test_extra])

    encoders = {}
    y_train_list = []
    y_dev_list = []

    for col in ATTRIBUTES:
        le = LabelEncoder()
        y_tr = le.fit_transform(df_train_label_sorted[col].astype(str))

        y_dv = df_dev_label_sorted[col].astype(str).map(
            lambda x: le.transform([x])[0] if x in le.classes_ else -1
        ).values

        encoders[col] = le
        y_train_list.append(y_tr)
        y_dev_list.append(y_dv)
    
    y_train = np.column_stack(y_train_list)
    y_dev = np.column_stack(y_dev_list)

    return X_train, X_dev, y_train, y_dev, encoders, df_dev_sorted, X_test, df_test


X_train, X_dev, y_train, y_dev, encoders, df_dev_sorted, X_test, df_test = data_prep()
print("Data prep ready")

f1_per_attr = []
y_pred_all = []
y_test_all = []

for i, attr in enumerate(ATTRIBUTES):
    print(f"Training {attr}...")
    clf = LogisticRegression(max_iter=1000, class_weight="balanced")
    clf.fit(X_train, y_train[:, i])
    y_pred = clf.predict(X_dev)
    y_pred_all.append(y_pred)
    y_test_pred = clf.predict(X_test)
    y_test_all.append(y_test_pred)

    f1 = f1_score(y_dev[:, i], y_pred, average="macro")
    f1_per_attr.append(f1)

print("Per-attribute F1:", dict(zip(ATTRIBUTES, f1_per_attr)))

y_pred_test_numeric = np.column_stack(y_test_all)
pred_df = pd.DataFrame()
pred_df["client_id"] = df_test["client_id"].values

for i, attr in enumerate(ATTRIBUTES):
    le = encoders[attr]
    pred_df[attr] = le.inverse_transform(y_pred_test_numeric[:, i])

pred_df.to_csv("test_predictions.csv", index=False)
print("prediction is saved.")






