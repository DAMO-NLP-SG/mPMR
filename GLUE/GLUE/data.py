#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import torch
from torch.utils.data import Dataset
from transformers.tokenization_utils_base import TruncationStrategy
from transformers.utils import logging
import random
import numpy as np
logger = logging.get_logger(__name__)
MULTI_SEP_TOKENS_TOKENIZERS_SET = {"roberta", "camembert", "bart", "mpnet"}
random.seed(42)


def compute_acc(preds, labels):
    """ simple accuracy """
    preds = np.array(preds)
    labels = np.array(labels)
    acc = float((preds == labels).mean())
    return {'acc': acc}

class GLUEDataset(Dataset):
    def __init__(self, dataset, data_path, tokenizer: None, max_length: int = 512, max_query_length=64, allow_tok=False):
        self.data_name = data_path
        self.tokenizer = tokenizer
        self.get_data(data_path, dataset)
        self.max_length = max_length
        self.max_query_length = max_query_length
        self.allow_tok = allow_tok
    def get_data(self, data_path, dataset):
        if data_path == "MNLI":
            self.all_data = []
            self.compute_metric = compute_acc
            label_dict = {"neutral": 0, 'entailment': 1, 'contradiction': 2}
            for i, item in enumerate(dataset):
                if item["gold_label"] != '-':
                    passage = "hypothesis: " + item["sentence1"] + " premise: " + item["sentence2"]
                    data_one = {
                        'passage': passage,
                        'labels': ["neutral. The hypothesis is a sentence with mostly the same lexical items as the premise but a different meaning.",
                                   'entailment. The hypothesis is a sentence with a similar meaning as the premise.',
                                   'contradiction. The hypothesis is a sentence with a contradictory meaning to the premise.'],
                        "gold_label": label_dict[item["gold_label"]],
                    }
                    self.all_data.append(data_one)
        elif data_path.startswith("SST-2"):
            self.all_data = []
            self.compute_metric = compute_acc
            for i, item in enumerate(dataset):
                if i == 0:
                    continue
                else:
                    passage = item[0]
                    data_one = {
                        'passage': passage,
                        'labels': ['negative. bad, feeling not good.', 'positive. good, having a good feeling.'],
                        "gold_label": int(item[1]),
                    }
                self.all_data.append(data_one)
        else:
            raise NotImplementedError
    def __len__(self):
        return len(self.all_data)
    def __getitem__(self, item):
        """
        Args:
            item: int, idx
        Returns:
            tokens: tokens of query + context, [seq_len]
            attention_mask: attention mask, 1 for token, 0 for padding, [seq_len]
            token_type_ids: token type ids, 0 for query, 1 for context, [seq_len]
            label_mask: label mask, 1 for counting into loss, 0 for ignoring. [seq_len]
            match_labels: match labels, [seq_len, seq_len]
        """
        data = self.all_data[item]
        passage = data['passage']
        labels = data['labels']
        gold_label = data['gold_label']
        tokenizer = self.tokenizer
        tokenizer_type = type(tokenizer).__name__.replace("Tokenizer", "").lower()
        sequence_added_tokens = (
            tokenizer.model_max_length - tokenizer.max_len_single_sentence + 1
            if tokenizer_type in MULTI_SEP_TOKENS_TOKENIZERS_SET
            else tokenizer.model_max_length - tokenizer.max_len_single_sentence
        )


        if tokenizer.__class__.__name__ in [
            "RobertaTokenizer",
            "LongformerTokenizer",
            "BartTokenizer",
            "RobertaTokenizerFast",
            "LongformerTokenizerFast",
            "BartTokenizerFast",
        ]:
            passage_token = tokenizer.tokenize(passage, add_prefix_space=True)
        elif tokenizer.__class__.__name__ in [
            'BertTokenizer'
        ]:
            passage_token = tokenizer.tokenize(passage)
        elif tokenizer.__class__.__name__ in [
            'BertWordPieceTokenizer'
        ]:
            passage_token = tokenizer.encode(passage, add_special_tokens=False).tokens
        else:
            passage_token = tokenizer.tokenize(passage)

        spans = []
        for (i_c, token) in enumerate(labels):
            if tokenizer.__class__.__name__ in [
                "RobertaTokenizer",
                "LongformerTokenizer",
                "BartTokenizer",
                "RobertaTokenizerFast",
                "LongformerTokenizerFast",
                "BartTokenizerFast",
            ]:
                all_label_tokens = tokenizer.tokenize(token, add_prefix_space=True)
            elif tokenizer.__class__.__name__ in [
                'BertTokenizer'
            ]:
                all_label_tokens = tokenizer.tokenize(token)
            elif tokenizer.__class__.__name__ in [
                'BertWordPieceTokenizer'
            ]:
                all_label_tokens = tokenizer.encode(token, add_special_tokens=False).tokens
            else:
                all_label_tokens = tokenizer.tokenize(token)

            truncated_query = tokenizer.encode(
                all_label_tokens, add_special_tokens=False, truncation=True, max_length=self.max_query_length
            )


            truncation = TruncationStrategy.ONLY_SECOND.value
            padding_strategy = "do_not_pad"

            encoded_dict = tokenizer.encode_plus(  # TODO(thom) update this logic
                truncated_query,
                passage_token,
                truncation=truncation,
                padding=padding_strategy,
                max_length=self.max_length,
                return_overflowing_tokens=True,
                return_token_type_ids=True,
            )
            tokens = encoded_dict['input_ids']
            type_ids = encoded_dict['token_type_ids']
            attn_mask = encoded_dict['attention_mask']

            seq_len = len(tokens)
            match_labels = torch.zeros([seq_len, seq_len], dtype=torch.long)
            if i_c == gold_label:
                match_labels[0, 0] = 1
            if not self.allow_tok:
                label_mask = [1] + [0] * (len(tokens) - 1)
            else:
                label_mask = [1] + [0] * (len(truncated_query) + sequence_added_tokens - 1) + [1] * (seq_len - len(truncated_query) - sequence_added_tokens - 1) + [0]


            assert len(label_mask) == len(tokens)
            span = [
            torch.LongTensor(tokens),
            torch.LongTensor(attn_mask),
            torch.LongTensor(type_ids),
            torch.LongTensor(label_mask),
            match_labels,
            torch.LongTensor([gold_label]),
            item,
            ]
            spans.append(span)

        return spans


