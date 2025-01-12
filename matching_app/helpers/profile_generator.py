# %%
from transformers import pipeline
from sentence_transformers import SentenceTransformer
import pandas as pd
from scipy.spatial.distance import cosine
import numpy as np
from ast import literal_eval
from detoxify import Detoxify

# %%
embedding_series = pd.read_csv('../data/embedding_series.csv').set_index('Unnamed: 0')
df_all = pd.read_csv('../data/okcupid_profiles.csv')
df_all = df_all.loc[embedding_series.index,:] 
matches = pd.read_csv('../data/okcupid_matches.csv').set_index('Unnamed: 0')
model = SentenceTransformer('all-MiniLM-L6-v2')
toxic_model = Detoxify("original")

# %%
def rank_new_input(input_str, df_all, model, embedding_series, eval_fake = False, pref_gender=False, pref_age_lower=False, pref_age_higher=False, min_similarity_score = 0.5):
    '''
    Take in a new input, create embeddings, and calculate cosine similarity, 
    then compare to all other potential partners in the dataset and return a ranked list of matches. 
    If evaluating a fake profile in relation to an input string, also add that to the data frame to be ranked. 
    '''
    df_possible = df_all.copy()
    if pref_gender:
        df_possible = df_possible.loc[df_possible.loc[:,'sex'] == pref_gender, :]
    if pref_age_higher:
        df_possible = df_possible[df_possible.loc[:, "age"] <= pref_age_higher]
    if pref_age_lower:
        df_possible = df_possible[df_possible.loc[:, "age"] >= pref_age_lower]
    user_embeddings = model.encode(input_str)
    if eval_fake:
        #ADD FAKE PROFILE STRING TO EMBEDDING SERIES and df_possible so that it will rank accordingly
        embedding_series.loc[99999, 'embedding'] = str(model.encode(eval_fake).tolist())
        fake_profile_row = pd.DataFrame([np.nan] * len(df_possible.columns)).T
        fake_profile_row.index = [99999]
        df_possible = pd.concat([df_possible, fake_profile_row]) 

    other_embeddings = [literal_eval(embedding_series.loc[i,'embedding']) for i in df_possible.index]
    # Compute the cosine similarity between the user's weighted embedding vector and all possible matches
    cosine_similarities = compute_cosine_similarity(user_embeddings, other_embeddings)
    # Recover index to match back to original dataframe
    similarity_scores = [(df_possible.index[index], score) for index, score in enumerate(cosine_similarities) if score >= min_similarity_score and score != 1]
    # Sort by similarity
    ranked_similarity = sorted(similarity_scores, key = lambda x: x[1], reverse = True)
    return ranked_similarity

def compute_cosine_similarity(target_vector, vectors):
    '''
    Compute cosine similarity between one vector and many others
    '''
    similarities = []
    for vector in vectors:
        similarity = 1 - cosine(target_vector, vector)  # 1 - cosine distance to get cosine similarity
        similarities.append(similarity)
    return similarities

# %%
def construct_prompt(input_string, matches, num_char = False):
    '''
    Take an input string and the top matches for that person, 
    then build a few shot learning prompt to illustrate what the essays of a good match look like. 
    '''
    slice_len = min(2, len(matches))
    top_matches_slice = matches[:slice_len]
    essays_to_use = ["essay0", "essay1", "essay2", "essay3", "essay4", 
                   "essay5", "essay6", "essay7", "essay8"]
    prompt = 'Write a dating profile that would be a good match for the input person ' + "Input: " + input_string
    for i, val in top_matches_slice:
        essays_subset = df_all.loc[i,essays_to_use]
        output = essays_subset.str.cat()
        if num_char:
            output = output[:num_char]
        prompt = prompt  + " This is a good match: " + output
    return prompt + f"Input: {input_string}" + " Here is a new good match: "
    
# %%
def generate_profile(input_str, eval_fake = False, pref_gender=False, pref_age_lower=False, 
                     pref_age_higher=False, min_similarity_score = 0.65):
    '''
    Function to generate the profile.
    '''
    toxicity_rubric_input = toxic_model.predict(input_str)
    if toxicity_rubric_input['severe_toxicity'] > 0.1 or toxicity_rubric_input['threat'] > 0.01:
        return "Your generated match cannot be shown due to harmful material in your bio. Please modify and try again."
    
    embedding_series = pd.read_csv('../data/embedding_series.csv').set_index('Unnamed: 0')
    df_all = pd.read_csv('../data/okcupid_profiles.csv')
    df_all = df_all.loc[embedding_series.index,:] 
    model = SentenceTransformer('all-MiniLM-L6-v2')
    
    new_input_matches = rank_new_input(input_str, df_all, model, embedding_series, eval_fake, pref_gender,  
                    pref_age_lower, pref_age_higher, min_similarity_score)
    try: 
        prompt = construct_prompt(input_str, new_input_matches, 200)     
    except Exception as e:
        return "Sorry, we cannot deploy this method as you do not have enough matches in the current dataframe to use a generative model with."
    
    generator = pipeline('text-generation', model='gpt2')
    all_returned = generator(prompt, do_sample=True, temperature = 0.9, truncation = True,
                         min_length=200, max_length = 1000, num_return_sequences=1)
    fake_profile = all_returned[0]['generated_text'].replace(prompt, "").replace("This is a good match:", "")
    
    toxicity_rubric_generated = toxic_model.predict(fake_profile)
    ## Do not return generated text if it fails toxicity test
    if toxicity_rubric_generated['severe_toxicity'] > 0.1 or toxicity_rubric_generated['threat'] > 0.01:
        return "Your generated match cannot be shown. Please try again."

    return fake_profile
