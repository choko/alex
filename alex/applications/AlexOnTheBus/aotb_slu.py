#!/usr/bin/python
# encoding: utf8

from __future__ import unicode_literals
from collections import defaultdict

import autopath

from alex.components.asr.utterance import Utterance, UtteranceHyp
from alex.components.slu.base import SLUInterface
from alex.components.slu.da import DialogueActItem, \
    DialogueActConfusionNetwork, merge_slu_confnets
from alex.utils.czech_stemmer import cz_stem


def _fill_utterance_values(abutterance, category, res):
    for _, value in abutterance.insts_for_type((category.upper(), )):
        if value == ("[OTHER]", ):
            continue

        res[category].append(value)

def _any_word_in(utterance, words):
    for alt_expr in words:
        if alt_expr in utterance.utterance:
            return True
    return False

def _all_words_in(utterance, words):
    for alt_expr in words:
        if alt_expr not in utterance.utterance:
            return False
    return True


class AOTBSLU(SLUInterface):
    def __init__(self, preprocessing, cfg=None):
        super(AOTBSLU, self).__init__(preprocessing, cfg)

    def parse_stop(self, abutterance, cn):
        res = defaultdict(list)
        _fill_utterance_values(abutterance, 'stop', res)

        stop_name = None
        for slot, values in res.iteritems():
            for value in values:
                stop_name = u" ".join(value)
                break

        utt_set = set(abutterance)

        preps_from = set([u"z", u"za", u"ze", u"od", u"začátek"])
        preps_to = set([u"k", u"do", u"konec", u"na"])

        preps_from_used = preps_from.intersection(utt_set)
        preps_to_used = preps_to.intersection(utt_set)

        preps_from_in = len(preps_from_used) > 0
        preps_to_in = len(preps_to_used) > 0

#       this is not used in the DM, the do not generate
#        cn.add(1.0, DialogueActItem("inform", "stop", stop_name))

        if preps_from_in and not preps_to_in:
            cn.add(1.0,
                   DialogueActItem("inform", "from_stop", stop_name,
                                   attrs={'prep': next(iter(preps_from_used))})
                   )

        if not preps_from_in and preps_to_in:
            cn.add(1.0,
                   DialogueActItem("inform", "to_stop", stop_name,
                                   attrs={'prep': next(iter(preps_to_used))}))

        # backoff to default from
        if not preps_from_in and not preps_to_in:
            cn.add(1.0, DialogueActItem("inform", "from_stop", stop_name))
            
            
    def parse_time(self, abutterance, cn):
        res = defaultdict(list)
        _fill_utterance_values(abutterance, 'time', res)

        for slot, values in res.iteritems():
            for value in values:
                cn.add(1.0, DialogueActItem("inform", slot, " ".join(value)))
                break

    def parse_meta(self, utterance, cn):

        if _any_word_in(utterance, [u"ahoj",  u"nazdar", u"zdar", ]) or \
            _all_words_in(utterance, [u"dobrý",  u"den" ]):
            cn.add(1.0, DialogueActItem("hello"))
            
        if _any_word_in(utterance, [u"děkuji", u"nashledanou", u"shledanou", u"shle", u"nashle", u"díky",
                                        u"sbohem", u"zdar"]):
            cn.add(1.0, DialogueActItem("bye"))

        if _any_word_in(utterance, [u"jiný", u"jiné", u"jiná", u"další",
                                      u"dál", u"jiného"]):
            cn.add(1.0, DialogueActItem("reqalts"))

        if _any_word_in(utterance, [u"zopakovat",  u"opakovat", u"znovu", u"opakuj", u"zopakuj" ]) or \
            _all_words_in(utterance, [u"ještě",  u"jednou" ]):

            cn.add(1.0, DialogueActItem("repeat"))

        if _any_word_in(utterance, [u"nápověda",  u"pomoc", ]):
            cn.add(1.0, DialogueActItem("help"))

    def parse_1_best(self, utterance, verbose=False):
        """Parse an utterance into a dialogue act.
        """
        if isinstance(utterance, UtteranceHyp):
            # Parse just the utterance and ignore the confidence score.
            utterance = utterance.utterance

        if verbose:
            print 'Parsing utterance "{utt}".'.format(utt=utterance)
        
        if self.preprocessing:
            utterance = self.preprocessing.text_normalisation(utterance)
            abutterance, category_labels = \
                self.preprocessing.values2category_labels_in_utterance(utterance)
            if verbose:
                print 'After preprocessing: "{utt}".'.format(utt=abutterance)
                print category_labels
        else:
            category_labels = dict()
            
        res_cn = DialogueActConfusionNetwork()
        if 'STOP' in category_labels:
            self.parse_stop(abutterance, res_cn)
        elif 'TIME' in category_labels:
            self.parse_time(abutterance, res_cn)

        self.parse_meta(utterance, res_cn)

        if not res_cn:
            res_cn.add(1.0, DialogueActItem("other"))
            
        return res_cn

    def parse_nblist(self, utterance_list):
        """Parse N-best list by parsing each item in the list and then merging
        the results."""

        if len(utterance_list) == 0:
            return DialogueActConfusionNetwork()

        confnet_hyps = []
        for prob, utt in utterance_list:
            if "__other__" == utt:
                confnet = DialogueActConfusionNetwork()
                confnet.add(1.0, DialogueActItem("other"))
            else:
                confnet = self.parse_1_best(utt)

            confnet_hyps.append((prob, confnet))

            # print prob, utt
            # confnet.prune()
            # confnet.sort()
            # print confnet

        confnet = merge_slu_confnets(confnet_hyps)
        confnet.prune()
        confnet.sort()

        return confnet
        
    def parse_confnet(self, confnet, verbose=False):
        """Parse the confusion network by generating an N-best list and parsing
        this N-best list."""

        nblist = confnet.get_utterance_nblist(n=40)
        sem = self.parse_nblist(nblist)

        return sem        