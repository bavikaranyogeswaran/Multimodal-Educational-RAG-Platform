"""Tests for the deterministic QueryClassifier.

Each class covers one QueryClass via representative queries. Priority tests verify
that the first-match rule resolves conflicts between overlapping signals correctly.
"""

from __future__ import annotations

import pytest

from app.domain.enums import QueryClass
from app.domain.retrieval.classifier import QueryClassifier


@pytest.fixture
def clf() -> QueryClassifier:
    return QueryClassifier()


# ---------------------------------------------------------------------------
# EXACT_TERM
# ---------------------------------------------------------------------------


class TestExactTerm:
    def test_quoted_term(self, clf: QueryClassifier) -> None:
        assert clf.classify('"gradient descent" definition') == QueryClass.EXACT_TERM

    def test_define_request(self, clf: QueryClassifier) -> None:
        assert clf.classify("define entropy") == QueryClass.EXACT_TERM

    def test_definition_of(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is the definition of overfitting?") == QueryClass.EXACT_TERM

    def test_what_does_mean(self, clf: QueryClassifier) -> None:
        assert clf.classify("what does regularization mean?") == QueryClass.EXACT_TERM

    def test_labelled_equation(self, clf: QueryClassifier) -> None:
        assert clf.classify("explain Equation 3.2 in the text") == QueryClass.EXACT_TERM

    def test_labelled_theorem(self, clf: QueryClassifier) -> None:
        assert clf.classify("state Theorem 1.4") == QueryClass.EXACT_TERM


# ---------------------------------------------------------------------------
# TABLE
# ---------------------------------------------------------------------------


class TestTable:
    def test_table_number(self, clf: QueryClassifier) -> None:
        assert clf.classify("what does Table 3 show?") == QueryClass.TABLE

    def test_in_the_table(self, clf: QueryClassifier) -> None:
        assert clf.classify("find the value in the table") == QueryClass.TABLE

    def test_the_table_above(self, clf: QueryClassifier) -> None:
        assert clf.classify("interpret the table above") == QueryClass.TABLE

    def test_rows_from_the_table(self, clf: QueryClassifier) -> None:
        assert clf.classify("what do the rows in the table represent?") == QueryClass.TABLE


# ---------------------------------------------------------------------------
# VISUAL
# ---------------------------------------------------------------------------


class TestVisual:
    def test_figure_number(self, clf: QueryClassifier) -> None:
        assert clf.classify("what does Figure 4.2 illustrate?") == QueryClass.VISUAL

    def test_diagram(self, clf: QueryClassifier) -> None:
        assert clf.classify("explain the diagram on page 15") == QueryClass.VISUAL

    def test_flowchart(self, clf: QueryClassifier) -> None:
        assert clf.classify("describe the flowchart for the algorithm") == QueryClass.VISUAL

    def test_chart(self, clf: QueryClassifier) -> None:
        assert clf.classify("what trend does the chart show?") == QueryClass.VISUAL


# ---------------------------------------------------------------------------
# QUIZ_GENERATION
# ---------------------------------------------------------------------------


class TestQuizGeneration:
    def test_quiz_me(self, clf: QueryClassifier) -> None:
        assert clf.classify("quiz me on chapter 5") == QueryClass.QUIZ_GENERATION

    def test_generate_questions(self, clf: QueryClassifier) -> None:
        assert clf.classify("generate some questions about neural networks") == QueryClass.QUIZ_GENERATION

    def test_practice_problems(self, clf: QueryClassifier) -> None:
        assert clf.classify("give me some practice problems on backpropagation") == QueryClass.QUIZ_GENERATION

    def test_create_quiz(self, clf: QueryClassifier) -> None:
        assert clf.classify("create a quiz on supervised learning") == QueryClass.QUIZ_GENERATION

    def test_sample_questions(self, clf: QueryClassifier) -> None:
        assert clf.classify("give me sample questions about attention mechanisms") == QueryClass.QUIZ_GENERATION


# ---------------------------------------------------------------------------
# SUMMARY
# ---------------------------------------------------------------------------


class TestSummary:
    def test_summarize(self, clf: QueryClassifier) -> None:
        assert clf.classify("summarize chapter 3") == QueryClass.SUMMARY

    def test_key_points(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are the key points of section 2?") == QueryClass.SUMMARY

    def test_main_ideas(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are the main ideas covered in this chapter?") == QueryClass.SUMMARY

    def test_overview_of(self, clf: QueryClassifier) -> None:
        assert clf.classify("give me an overview of the topic") == QueryClass.SUMMARY

    def test_key_takeaways(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are the key takeaways from this section?") == QueryClass.SUMMARY


# ---------------------------------------------------------------------------
# CONCEPT_MAP
# ---------------------------------------------------------------------------


class TestConceptMap:
    def test_concept_map(self, clf: QueryClassifier) -> None:
        assert clf.classify("create a concept map for machine learning") == QueryClass.CONCEPT_MAP

    def test_how_everything_fits(self, clf: QueryClassifier) -> None:
        assert clf.classify("how does everything fit together in this chapter?") == QueryClass.CONCEPT_MAP

    def test_map_out_concepts(self, clf: QueryClassifier) -> None:
        assert clf.classify("map out all the concepts in the chapter") == QueryClass.CONCEPT_MAP

    def test_mind_map(self, clf: QueryClassifier) -> None:
        assert clf.classify("mind map for deep learning") == QueryClass.CONCEPT_MAP


# ---------------------------------------------------------------------------
# COMPARISON
# ---------------------------------------------------------------------------


class TestComparison:
    def test_compare(self, clf: QueryClassifier) -> None:
        assert clf.classify("compare supervised and unsupervised learning") == QueryClass.COMPARISON

    def test_difference_between(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is the difference between SVM and neural networks?") == QueryClass.COMPARISON

    def test_versus(self, clf: QueryClassifier) -> None:
        assert clf.classify("ReLU vs sigmoid: which is better?") == QueryClass.COMPARISON

    def test_distinguish_between(self, clf: QueryClassifier) -> None:
        assert clf.classify("distinguish between precision and recall") == QueryClass.COMPARISON

    def test_how_differ(self, clf: QueryClassifier) -> None:
        assert clf.classify("how do batch normalization and dropout differ?") == QueryClass.COMPARISON

    def test_similarities_between(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are the similarities between bagging and boosting?") == QueryClass.COMPARISON


# ---------------------------------------------------------------------------
# AGGREGATION
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_how_many(self, clf: QueryClassifier) -> None:
        assert clf.classify("how many activation functions are mentioned in chapter 2?") == QueryClass.AGGREGATION

    def test_list_all(self, clf: QueryClassifier) -> None:
        assert clf.classify("list all the types of regularization") == QueryClass.AGGREGATION

    def test_total_number_of(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is the total number of layers in the network?") == QueryClass.AGGREGATION

    def test_all_types_of(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are all the types of loss functions?") == QueryClass.AGGREGATION


# ---------------------------------------------------------------------------
# MULTI_DOCUMENT
# ---------------------------------------------------------------------------


class TestMultiDocument:
    def test_across_documents(self, clf: QueryClassifier) -> None:
        assert clf.classify("how is this topic treated across all the documents?") == QueryClass.MULTI_DOCUMENT

    def test_in_multiple_papers(self, clf: QueryClassifier) -> None:
        assert clf.classify("in multiple papers, how is attention defined?") == QueryClass.MULTI_DOCUMENT

    def test_multiple_sources(self, clf: QueryClassifier) -> None:
        assert clf.classify("how is this concept presented across multiple sources?") == QueryClass.MULTI_DOCUMENT


# ---------------------------------------------------------------------------
# MULTI_HOP
# ---------------------------------------------------------------------------


class TestMultiHop:
    def test_if_then(self, clf: QueryClassifier) -> None:
        assert clf.classify(
            "if the learning rate is too high, then what happens to convergence?"
        ) == QueryClass.MULTI_HOP

    def test_given_that(self, clf: QueryClassifier) -> None:
        assert clf.classify(
            "given that overfitting occurs, what should be adjusted?"
        ) == QueryClass.MULTI_HOP

    def test_trace_through(self, clf: QueryClassifier) -> None:
        assert clf.classify("trace through the backpropagation algorithm") == QueryClass.MULTI_HOP

    def test_chain_of_reasoning(self, clf: QueryClassifier) -> None:
        assert clf.classify(
            "explain the chain of reasoning behind gradient clipping"
        ) == QueryClass.MULTI_HOP

    def test_derive(self, clf: QueryClassifier) -> None:
        assert clf.classify("derive the gradient from the loss function") == QueryClass.MULTI_HOP


# ---------------------------------------------------------------------------
# RELATIONSHIP
# ---------------------------------------------------------------------------


class TestRelationship:
    def test_relationship_between(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is the relationship between bias and variance?") == QueryClass.RELATIONSHIP

    def test_how_does_affect(self, clf: QueryClassifier) -> None:
        assert clf.classify("how does batch size affect training speed?") == QueryClass.RELATIONSHIP

    def test_connection_between(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is the connection between entropy and cross-entropy?") == QueryClass.RELATIONSHIP

    def test_how_related_to(self, clf: QueryClassifier) -> None:
        assert clf.classify("how is dropout related to regularization?") == QueryClass.RELATIONSHIP

    def test_how_does_influence(self, clf: QueryClassifier) -> None:
        assert clf.classify("how does learning rate influence convergence?") == QueryClass.RELATIONSHIP


# ---------------------------------------------------------------------------
# PREREQUISITE
# ---------------------------------------------------------------------------


class TestPrerequisite:
    def test_prerequisite(self, clf: QueryClassifier) -> None:
        assert clf.classify("what are the prerequisites for understanding transformers?") == QueryClass.PREREQUISITE

    def test_what_do_i_need_to_know(self, clf: QueryClassifier) -> None:
        assert clf.classify(
            "what do I need to know before learning about backpropagation?"
        ) == QueryClass.PREREQUISITE

    def test_background_needed(self, clf: QueryClassifier) -> None:
        assert clf.classify("what background knowledge is needed for this topic?") == QueryClass.PREREQUISITE

    def test_foundational_knowledge(self, clf: QueryClassifier) -> None:
        assert clf.classify("foundational knowledge for deep learning") == QueryClass.PREREQUISITE


# ---------------------------------------------------------------------------
# DIRECT (fallback)
# ---------------------------------------------------------------------------


class TestDirect:
    def test_plain_how_question(self, clf: QueryClassifier) -> None:
        assert clf.classify("how does gradient descent work?") == QueryClass.DIRECT

    def test_explain_request(self, clf: QueryClassifier) -> None:
        assert clf.classify("explain the attention mechanism") == QueryClass.DIRECT

    def test_what_is_question(self, clf: QueryClassifier) -> None:
        assert clf.classify("what is a neural network?") == QueryClass.DIRECT

    def test_empty_string(self, clf: QueryClassifier) -> None:
        assert clf.classify("") == QueryClass.DIRECT

    def test_generic_question(self, clf: QueryClassifier) -> None:
        assert clf.classify("tell me about convolutional layers") == QueryClass.DIRECT


# ---------------------------------------------------------------------------
# Priority (first-match wins)
# ---------------------------------------------------------------------------


class TestPriority:
    def test_exact_term_beats_summary(self, clf: QueryClassifier) -> None:
        # Quoted text triggers EXACT_TERM before "main" could trigger SUMMARY.
        assert clf.classify('"main idea" of the paper') == QueryClass.EXACT_TERM

    def test_table_beats_summary(self, clf: QueryClassifier) -> None:
        # "key points" matches SUMMARY; "table 2" matches TABLE which ranks higher.
        assert clf.classify("what are the key points in table 2?") == QueryClass.TABLE

    def test_comparison_beats_aggregation(self, clf: QueryClassifier) -> None:
        # "compare" fires COMPARISON before "how many" can fire AGGREGATION.
        assert clf.classify("compare how many types each approach produces") == QueryClass.COMPARISON

    def test_case_insensitive_summary(self, clf: QueryClassifier) -> None:
        assert clf.classify("SUMMARIZE chapter 3") == QueryClass.SUMMARY

    def test_case_insensitive_exact_term(self, clf: QueryClassifier) -> None:
        assert clf.classify("DEFINE entropy") == QueryClass.EXACT_TERM

    def test_exact_term_beats_relationship(self, clf: QueryClassifier) -> None:
        # "what does X mean" is EXACT_TERM; it fires before RELATIONSHIP patterns.
        assert clf.classify("what does 'relate to' mean in this context?") == QueryClass.EXACT_TERM
