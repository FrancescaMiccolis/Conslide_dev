# Copyright 2022-present, Lorenzo Bonicelli, Pietro Buzzega, Matteo Boschini, Angelo Porrello, Simone Calderara.
# All rights reserved.
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy # needed (don't change it)
import importlib
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "1"
import sys
import socket
main_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(main_path)
sys.path.append(main_path + '/datasets')
sys.path.append(main_path + '/backbone')
sys.path.append(main_path + '/models')

from datasets import NAMES as DATASET_NAMES
from models import get_all_models
from argparse import ArgumentParser
from utils.args import add_management_args
from datasets import ContinualDataset
from utils.continual_training import train as ctrain
from datasets import get_dataset
from models import get_model
from utils.training import train
from utils.best_args import best_args
from utils.conf import set_random_seed
import setproctitle
import torch
import uuid
import datetime
import wandb
# from datasets.dataset_generic import Generic_MIL_Dataset

def lecun_fix():
    # Yann moved his website to CloudFlare. You need this now
    from six.moves import urllib
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)

def parse_args():
    parser = ArgumentParser(description='mammoth', allow_abbrev=False)
    parser.add_argument('--model', type=str, required=True,
                        help='Model name.', choices=get_all_models())
    parser.add_argument('--load_best_args', action='store_true',
                        help='Loads the best arguments for each method, '
                             'dataset and memory buffer.')
    torch.set_num_threads(4)
    add_management_args(parser)
    args = parser.parse_known_args()[0]
    mod = importlib.import_module('models.' + args.model)
    # import ipdb;ipdb.set_trace()
    if args.load_best_args:
        parser.add_argument('--dataset', type=str, required=True,
                            choices=DATASET_NAMES,
                            help='Which dataset to perform experiments on.')
        if hasattr(mod, 'Buffer'):
            parser.add_argument('--buffer_size', type=int, required=True,
                                help='The size of the memory buffer.')
        args = parser.parse_args()
        if args.model == 'joint':
            best = best_args[args.dataset]['sgd']
        else:
            best = best_args[args.dataset][args.model]
        if hasattr(mod, 'Buffer'):
            best = best[args.buffer_size]
        else:
            best = best[-1]
        # import ipdb;ipdb.set_trace()
        get_parser = getattr(mod, 'get_parser')
        parser = get_parser()
        to_parse = sys.argv[1:] + ['--' + k + '=' + str(v) for k, v in best.items()]
        to_parse.remove('--load_best_args')
        args = parser.parse_args(to_parse)
        if args.model == 'joint' and args.dataset == 'mnist-360':
            args.model = 'joint_gcl'        
    else:
        get_parser = getattr(mod, 'get_parser')
        parser = get_parser()
        args = parser.parse_args()

    args.seed = 12
    if args.seed is not None:
        set_random_seed(args.seed)

    args.cam = "excluded"
    args.debug_mode = 1
    args.loadonmemory = 0
    args.test_on_val = False

    return args

def main(fold, args=None):
    # for fold in range(5):
    lecun_fix()
    if args is None:
        args = parse_args()    
    
    # Add uuid, timestamp and hostname for logging
    args.conf_jobnum = str(uuid.uuid4())
    args.conf_timestamp = str(datetime.datetime.now())
    args.conf_host = socket.gethostname()
    dataset = get_dataset(args)
    # dataset = Generic_MIL_Dataset(csv_path = '/home/rock/Database3/WSI/Dataset/Camelyon16/camelyon16_label.csv',
    #                         data_dir= '/home/rock/data4/WSI_Data/Camelyon16/patch_4096/resnet50_l0l1/',
    #                         shuffle = False, 
    #                         seed = 0, 
    #                         print_info = True,
    #                         label_dict = {'normal':0, 'tumor':1},
    #                         patient_strat=False,
    #                         ignore=[])

    if args.n_epochs is None and isinstance(dataset, ContinualDataset):
        args.n_epochs = dataset.get_epochs()
    if args.batch_size is None:
        args.batch_size = dataset.get_batch_size()
    if hasattr(importlib.import_module('models.' + args.model), 'Buffer') and args.minibatch_size is None:
        args.minibatch_size = dataset.get_minibatch_size()

    backbone = dataset.get_backbone()
    loss = dataset.get_loss()
    model = get_model(args, backbone, loss, dataset.get_transform())
    args.fold = 0
    dataset.load(args.fold)
    
    # set job name
    # setproctitle.setproctitle('{}_{}_{}'.format(args.model, args.buffer_size if 'buffer_size' in args else 0, args.dataset))     
    setproctitle.setproctitle(f'{args.exp_desc}')

    args.wandb_tag = 'conslide_code'
    mode = 'disabled' if args.debug_mode else 'online'
    #mode = 'online'
    wandb.init(project='miccai_coomil', entity='miccai_coomil', config=vars(args),tags=[args.wandb_tag],
                   name=str(args.model), mode=mode)
    args.wandb_url = wandb.run.get_url()

    if isinstance(dataset, ContinualDataset):
        train(model, dataset, args, fold)
    else:
        assert not hasattr(model, 'end_task') or model.NAME == 'joint_gcl'
        ctrain(args)


if __name__ == '__main__':
    for fold in range(5):
        main(fold=fold)
