"""
Enhanced ML Recommendation Engine v2
=====================================
Features:
- TF-IDF + Cosine Similarity (Content-Based)
- User-User Collaborative Filtering
- Hybrid Recommendation (weighted)
- Learning Path Suggestions
- Cold Start Handling
- Difficulty-aware recommendations
"""

import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import warnings
warnings.filterwarnings('ignore')


class HybridRecommender:
    def __init__(self):
        self.courses_df = None
        self.tfidf_matrix = None
        self.cosine_sim = None
        self.vectorizer = TfidfVectorizer(
            stop_words='english',
            ngram_range=(1, 2),
            max_features=5000
        )
        self._load_courses()

    def _load_courses(self):
        try:
            self.courses_df = pd.read_csv('data/courses.csv')
            self.courses_df['combined_features'] = (
                self.courses_df['title'].fillna('') + ' ' +
                self.courses_df['description'].fillna('') + ' ' +
                self.courses_df['tags'].fillna('') + ' ' +
                self.courses_df['category'].fillna('') + ' ' +
                self.courses_df['difficulty'].fillna('') + ' ' +
                self.courses_df['instructor'].fillna('')
            )
            self._build_content_model()
        except Exception as e:
            print(f"Error loading courses: {e}")

    def _build_content_model(self):
        self.tfidf_matrix = self.vectorizer.fit_transform(
            self.courses_df['combined_features']
        )
        self.cosine_sim = cosine_similarity(self.tfidf_matrix, self.tfidf_matrix)

    def reload(self):
        self._load_courses()

    # ── Content-Based ──
    def content_based_recommend(self, course_id, top_n=10):
        try:
            idx = self.courses_df[self.courses_df['course_id'] == course_id].index[0]
            sim_scores = list(enumerate(self.cosine_sim[idx]))
            sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
            sim_scores = sim_scores[1:top_n + 1]
            course_indices = [i[0] for i in sim_scores]
            return self.courses_df.iloc[course_indices]['course_id'].tolist()
        except Exception:
            return []

    def interest_based_recommend(self, interests, top_n=10):
        try:
            if not interests:
                return self.get_popular_courses(top_n)
            interest_vec = self.vectorizer.transform([interests])
            sim_scores = cosine_similarity(interest_vec, self.tfidf_matrix).flatten()
            top_indices = sim_scores.argsort()[::-1][:top_n]
            return self.courses_df.iloc[top_indices]['course_id'].tolist()
        except Exception:
            return self.get_popular_courses(top_n)

    # ── Collaborative Filtering ──
    def collaborative_recommend(self, user_id, all_ratings, top_n=10):
        try:
            if not all_ratings or len(all_ratings) < 2:
                return []
            ratings_df = pd.DataFrame(all_ratings)
            if ratings_df.empty or user_id not in ratings_df['user_id'].values:
                return []
            user_item_matrix = ratings_df.pivot_table(
                index='user_id', columns='course_id',
                values='rating', fill_value=0
            )
            if user_id not in user_item_matrix.index:
                return []
            user_sim = cosine_similarity(user_item_matrix)
            user_sim_df = pd.DataFrame(
                user_sim,
                index=user_item_matrix.index,
                columns=user_item_matrix.index
            )
            similar_users = user_sim_df[user_id].drop(user_id).sort_values(ascending=False)
            if similar_users.empty:
                return []
            top_similar = similar_users.head(5).index.tolist()
            user_rated = set(ratings_df[ratings_df['user_id'] == user_id]['course_id'].tolist())
            recommended = {}
            for sim_user in top_similar:
                sim_weight = similar_users[sim_user]
                sim_user_courses = ratings_df[
                    (ratings_df['user_id'] == sim_user) &
                    (ratings_df['rating'] >= 4) &
                    (~ratings_df['course_id'].isin(user_rated))
                ]
                for _, row in sim_user_courses.iterrows():
                    cid = row['course_id']
                    score = row['rating'] * sim_weight
                    recommended[cid] = recommended.get(cid, 0) + score
            sorted_recs = sorted(recommended.items(), key=lambda x: x[1], reverse=True)
            return [cid for cid, _ in sorted_recs[:top_n]]
        except Exception as e:
            print(f"Collaborative error: {e}")
            return []

    # ── Hybrid ──
    def hybrid_recommend(self, user_id, user_interests, learning_history,
                          all_ratings, top_n=10, user_level='Beginner'):
        already_seen = set(learning_history)
        scores = {}

        collab_recs = self.collaborative_recommend(user_id, all_ratings, top_n * 2)
        for rank, cid in enumerate(collab_recs):
            if cid not in already_seen:
                scores[cid] = scores.get(cid, 0) + (0.40 * (1 / (rank + 1)))

        if learning_history:
            for hist_course in learning_history[-5:]:
                cb_recs = self.content_based_recommend(hist_course, top_n)
                for rank, cid in enumerate(cb_recs):
                    if cid not in already_seen:
                        scores[cid] = scores.get(cid, 0) + (0.35 * (1 / (rank + 1)))

        interest_recs = self.interest_based_recommend(user_interests, top_n * 2)
        for rank, cid in enumerate(interest_recs):
            if cid not in already_seen:
                scores[cid] = scores.get(cid, 0) + (0.25 * (1 / (rank + 1)))

        # Boost courses matching user level
        level_map = {'Beginner': 1.2, 'Intermediate': 1.1, 'Advanced': 1.0}
        boost = level_map.get(user_level, 1.0)
        for cid in list(scores.keys()):
            course = self.courses_df[self.courses_df['course_id'] == cid]
            if not course.empty and course.iloc[0]['difficulty'] == user_level:
                scores[cid] *= boost

        if scores:
            sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            return [cid for cid, _ in sorted_scores[:top_n]]
        else:
            result = self.get_popular_courses(top_n)
            return [c for c in result if c not in already_seen]

    # ── Learning Path ──
    def get_learning_path(self, category, current_level='Beginner'):
        """Suggest a progressive learning path"""
        level_order = ['Beginner', 'Intermediate', 'Advanced']
        path = []
        cat_courses = self.courses_df[
            self.courses_df['category'] == category
        ].sort_values('rating', ascending=False)

        for level in level_order:
            level_courses = cat_courses[cat_courses['difficulty'] == level]
            if not level_courses.empty:
                path.append({
                    'level': level,
                    'courses': level_courses.head(2)['course_id'].tolist()
                })
        return path

    # ── Utility ──
    def get_popular_courses(self, top_n=10):
        popular = self.courses_df.sort_values('rating', ascending=False)
        return popular['course_id'].head(top_n).tolist()

    def get_courses_by_ids(self, course_ids):
        if not course_ids:
            return []
        result = self.courses_df[self.courses_df['course_id'].isin(course_ids)]
        # Maintain order
        result = result.set_index('course_id').loc[
            [c for c in course_ids if c in result['course_id'].values]
        ].reset_index()
        return result.to_dict('records')

    def get_all_courses(self):
        return self.courses_df.to_dict('records')

    def get_course_by_id(self, course_id):
        result = self.courses_df[self.courses_df['course_id'] == course_id]
        if result.empty:
            return None
        return result.iloc[0].to_dict()

    def search_courses(self, query, top_n=20):
        if not query:
            return self.get_all_courses()
        query_vec = self.vectorizer.transform([query])
        sim_scores = cosine_similarity(query_vec, self.tfidf_matrix).flatten()
        top_indices = sim_scores.argsort()[::-1][:top_n]
        return self.courses_df.iloc[top_indices].to_dict('records')

    def get_categories(self):
        return sorted(self.courses_df['category'].unique().tolist())

    def get_difficulties(self):
        return ['Beginner', 'Intermediate', 'Advanced']

    def get_trending_courses(self, top_n=6):
        return self.courses_df.nlargest(top_n, 'rating').to_dict('records')


recommender = HybridRecommender()
