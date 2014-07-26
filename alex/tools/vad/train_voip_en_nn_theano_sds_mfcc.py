#!/usr/bin/env python
# -*- coding: utf-8 -*-

import argparse
import sys
import numpy as np
import datetime
import random
import gc

from collections import deque

import autopath

from alex.utils.htk import *
from alex.ml import ffnn

""" This script trains NN for VAD.

"""

random.seed(0)
# the default values, these may be overwritten by the script parameters

max_frames = 100000 #1000000
max_files = 1000000
max_frames_per_segment = 50
trim_segments = 0
max_epoch = 20
hidden_units = 32
hidden_layers = 4
last_frames = 9
crossvalid_frames = int((0.20 * max_frames ))  # cca 20 % of all training data
usec0=0
usedelta=False
useacc=False
mel_banks_only=1
hidden_dropouts=0

#method = 'sg-fixedlr'
method = 'sg-rprop'
#method = 'sg-adalr'
#method = 'ng-fixedlr'
#method = 'ng-rprop'
#method = 'ng-adalr'
hact = 'tanh'
#hact = 'sigmoid'
#hact = 'softplus'
#hact = 'relu'
learning_rate = 5e-2
learning_rate_decay = 200.0
weight_l2=1e-6
batch_size= 50000 

fetures_file_name = "model_voip/vad_sds_mfcc_lf%d_mfr%d_mfl%d_mfps%d_ts%d_usec0%d_usedelta%d_useacc%d_mbo%d.npc" % \
                             (last_frames, max_frames, max_files, max_frames_per_segment, trim_segments, 
                              usec0, usedelta, useacc, mel_banks_only)


def load_mlf(train_data_sil_aligned, max_files, max_frames_per_segment):
    """ Loads a MLF file and creates normalised MLF class.

    :param train_data_sil_aligned:
    :param max_files:
    :param max_frames_per_segment:
    :return:
    """
    mlf = MLF(train_data_sil_aligned, max_files=max_files)
    mlf.filter_zero_segments()
    # map all sp, _noise_, _laugh_, _inhale_ to sil
    mlf.sub('sp', 'sil')
    mlf.sub('_noise_', 'sil')
    mlf.sub('_laugh_', 'sil')
    mlf.sub('_inhale_', 'sil')
    # map everything except of sil to speech
    mlf.sub('sil', 'speech', False)
    mlf.merge()
    #mlf_sil.times_to_seconds()
    mlf.times_to_frames()
    mlf.trim_segments(trim_segments)
    mlf.shorten_segments(max_frames_per_segment)

    return mlf


def get_accuracy(true_y, predictions_y):
    """ Compute accuracy of predictions from the activation of the last NN layer, and the sil prior probability.

    :param ds: the training dataset
    :param a: activation from the NN using the ds datasat
    """
    acc = np.mean(np.equal(np.argmax(predictions_y, axis=1),true_y))*100.0
    sil = (1.0-float(np.count_nonzero(true_y)) / len(true_y))*100.0

    return acc, sil

def train_nn(speech_data, speech_alignment):
    print
    print datetime.datetime.now()
    print
    random.seed(0)
    try:
        f = open(fetures_file_name, "rb")
        crossvalid_x = np.load(f) 
        crossvalid_y = np.load(f)
        train_x = np.load(f)
        train_y = np.load(f)
        f.close()
            
    except:        
        vta = MLFMFCCOnlineAlignedArray(usec0=usec0,n_last_frames=last_frames, usedelta = usedelta, useacc = useacc, mel_banks_only = mel_banks_only)
        sil_count = 0
        speech_count = 0
        for sd, sa in zip(speech_data, speech_alignment):
            mlf_speech = load_mlf(sa, max_files, max_frames_per_segment)
            vta.append_mlf(mlf_speech)
            vta.append_trn(sd)

            sil_count += mlf_speech.count_length('sil')
            speech_count += mlf_speech.count_length('speech')

        print "The length of sil segments:    ", sil_count
        print "The length of speech segments: ", speech_count

        mfcc = vta.__iter__().next()

        print "MFCC length:", len(mfcc[0])
        input_size = len(mfcc[0])

        print "Generating the cross-validation and train MFCC features"
        crossvalid_x = []
        crossvalid_y = []
        train_x = []
        train_y = []
        i = 0
        for frame, label in vta:
            # downcast
            frame = frame.astype(np.float32)
    #        frame = frame - (10.0 if mel_banks_only else 0.0)

            if i % (max_frames / 10) == 0:
                print "Already processed: %.2f%% of data" % (100.0*i/max_frames)

            if i > max_frames:
                break

            if random.random() < float(crossvalid_frames)/max_frames:
                # sample validation (test) data
                crossvalid_x.append(frame)
                if label == "sil":
                    crossvalid_y.append(0)
                else:
                    crossvalid_y.append(1)
            else:
                train_x.append(frame)
                if label == "sil":
                    train_y.append(0)
                else:
                    train_y.append(1)

            i += 1

        gc.collect()
        crossvalid_x = np.array(crossvalid_x).astype(np.float32)
        gc.collect()
        crossvalid_y = np.array(crossvalid_y).astype('int32')
        gc.collect()
        train_x = np.array(train_x).astype(np.float32)
        gc.collect()
        train_y = np.array(train_y).astype('int32')
        gc.collect()
        
        # normalise the data
        tx_m = np.mean(train_x, axis=0)
        tx_std = np.std(train_x, axis=0)
        
        gc.collect()
        crossvalid_x -= tx_m
        gc.collect()
        crossvalid_x /= tx_std
        gc.collect()
        train_x -= tx_m
        gc.collect()
        train_x /= tx_std
        gc.collect()

        print 'Saving data to:', fetures_file_name
        f = open(fetures_file_name, "wb")
        np.save(f, crossvalid_x) 
        np.save(f, crossvalid_y)
        np.save(f, train_x)
        np.save(f, train_y)
        f.close()
            
    print
    print datetime.datetime.now()
    print
    print "The shape of training data: ", train_x.shape, train_y.shape
    print "The shape of test data:     ", crossvalid_x.shape, crossvalid_y.shape
    print

    input_size = train_x.shape[1]
    
    e = ffnn.TheanoFFNN2(input_size, hidden_units, hidden_layers, 2, hidden_activation = hact, weight_l2 = weight_l2)


    dc_acc = []
    dt_acc = []

    epoch = 0
    while True:

        print
        print '-'*80
        print 'Predictions'
        print '-'*80
        predictions_y = e.predict(crossvalid_x, batch_size)
        c_acc, c_sil = get_accuracy(crossvalid_y, predictions_y)
        predictions_y = e.predict(train_x, batch_size)
        t_acc, t_sil = get_accuracy(train_y, predictions_y)

        dc_acc.append(c_acc)
        dt_acc.append(t_acc)

        print
        print "method, hact, max_frames, max_files, max_frames_per_segment, trim_segments, batch_size, max_epoch, hidden_units, last_frames, crossvalid_frames, usec0, usedelta, useacc, mel_banks_only "
        print method, hact, max_frames, max_files, max_frames_per_segment, trim_segments, batch_size, max_epoch, hidden_units, last_frames, crossvalid_frames, usec0, usedelta, useacc, mel_banks_only 
        print "Epoch: %d" % (epoch,)
        print
        print "Cross-validation stats"
        print "------------------------"
        print "Epoch predictive accuracy:  %0.4f" % c_acc
        print "Last epoch accs:", ["%.4f" % x for x in dc_acc[-20:]]
        print "Epoch sil bias: %0.2f" % c_sil
        print
        print "Training stats"
        print "------------------------"
        print "Epoch predictive accuracy:  %0.4f" % t_acc
        print "Last epoch accs:", ["%.4f" % x for x in dt_acc[-20:]]
        print "Epoch sil bias: %0.2f" % t_sil
        print
        print "Best results"
        print "------------------------"
        print "Best iteration:", np.argmax(dc_acc)
        print "Best iteration - cross-validation acc: %.4f" % dc_acc[np.argmax(dc_acc)]
        print "Best iteration - training acc:         %.4f" % dt_acc[np.argmax(dc_acc)]
        print
        print datetime.datetime.now()
        print

        if epoch == np.argmax(dc_acc):
            print
            print "Saving the FFNN model"
            print

            nn = ffnn.FFNN()
            for w, b in e.params:
                  nn.add_layer(w.get_value(), b.get_value())
            nn.save(file_name = "model_voip/vad_sds_mfcc_is%d_hu%d_lf%d_mfr%d_mfl%d_mfps%d_ts%d_usec0%d_usedelta%d_useacc%d_mbo%d.nnt" % \
                                 (input_size, hidden_units, last_frames, max_frames, max_files, max_frames_per_segment, trim_segments, 
                                 usec0, usedelta, useacc, mel_banks_only))
        
        if epoch == max_epoch:
            break
        epoch += 1

        print
        print '-'*80
        print 'Training'
        print '-'*80
        e.train(train_x, train_y, method = method, learning_rate=learning_rate*learning_rate_decay/(learning_rate_decay+epoch), batch_size = batch_size)


##################################################

def main():
    global method, batch_size, hact
    global max_frames, max_files, max_frames_per_segment, trim_segments, max_epoch, hidden_units, last_frames, crossvalid_frames, usec0
    global hidden_dropouts, weight_l2
    global mel_banks_only
    global fetures_file_name

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="""This program trains neural network VAD models using the theanets library.
      """)

    parser.add_argument('--method', action="store", default=method, type=str,
                        help='an optimisation method: default %s' % method)
    parser.add_argument('--hact', action="store", default=hact, type=str,
                        help='an hidden layers activation: default %s' % hact)
    parser.add_argument('--batch_size', action="store", default=batch_size, type=int,
                        help='a mini batch size: default %d' % batch_size)
    parser.add_argument('--max_frames', action="store", default=max_frames, type=int,
                        help='a number of frames used in training including the frames for the cross validation: default %d' % max_frames)
    parser.add_argument('--max_files', action="store", default=max_files, type=int,
                        help='a number of files from the MLF files used in training: default %d' % max_files)
    parser.add_argument('--max_frames_per_segment', action="store", default=max_frames_per_segment, type=int,
                        help='a maximum number of frames per segment (segment is a sequence of frames with the same label): default %d' % max_frames_per_segment)
    parser.add_argument('--trim_segments', action="store", default=trim_segments, type=int,
                        help='number of frames that are trimmed for beginning and the end of each segment: default %d' % trim_segments)
    parser.add_argument('--max_epoch', action="store", default=max_epoch, type=int,
                        help='number of training epochs: default %d' % max_epoch)
    parser.add_argument('--hidden_units', action="store", default=hidden_units, type=int,
                        help='number of hidden units: default %d' % hidden_units)
    parser.add_argument('--last_frames', action="store", default=last_frames, type=int,
                        help='number of last frames: default %d' % last_frames)
    parser.add_argument('--usec0', action="store", default=usec0, type=int,
                        help='use c0 in mfcc: default %d' % usec0)
    parser.add_argument('--mel_banks_only', action="store", default=mel_banks_only, type=int,
                        help='use mel banks only instead of mfcc: default %d' % mel_banks_only)
    parser.add_argument('--hidden_dropouts', action="store", default=hidden_dropouts, type=float,
                        help='proportion of hidden_dropouts: default %d' % hidden_dropouts)
    parser.add_argument('--weight_l2', action="store", default=weight_l2, type=float,
                        help='use weight L2 regularisation: default %d' % weight_l2)

    args = parser.parse_args()
    sys.argv = []

    method = args.method
    hact = args.hact
    batch_size = args.batch_size
    max_frames = args.max_frames
    max_files = args.max_files
    max_frames_per_segment = args.max_frames_per_segment
    trim_segments = args.trim_segments
    max_epoch = args.max_epoch
    hidden_units = args.hidden_units
    last_frames = args.last_frames
    crossvalid_frames = int((0.20 * max_frames ))  # cca 20 % of all training data
    usec0 = args.usec0
    mel_banks_only = args.mel_banks_only
    hidden_dropouts = args.hidden_dropouts
    weight_l2 = args.weight_l2


    # add all the training data
    train_speech = []
    train_speech_alignment = []

    train_speech.append('data_voip_en/train/*.wav')
    train_speech_alignment.append('model_voip_en/aligned_best.mlf')

    train_speech.append('data_voip_cs/train/*.wav')
    train_speech_alignment.append('model_voip_cs/aligned_best.mlf')


    fetures_file_name = "model_voip/vad_sds_mfcc_lf%d_mfr%d_mfl%d_mfps%d_ts%d_usec0%d_usedelta%d_useacc%d_mbo%d.npc" % \
                             (last_frames, max_frames, max_files, max_frames_per_segment, trim_segments, 
                              usec0, usedelta, useacc, mel_banks_only)

    print datetime.datetime.now()

    train_nn(train_speech, train_speech_alignment)

    print datetime.datetime.now()

if __name__ == "__main__":
    main()
