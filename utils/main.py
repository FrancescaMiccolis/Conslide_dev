# Copyright 2022-present, Lorenzo Bonicelli, Pietro Buzzega, Matteo Boschini, Angelo Porrello, Simone Calderara.
# All rights reserved.
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy # needed (don't change it)
import importlib
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "0"
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
import submitit
from utils.args import add_management_args
from utils.experiments import * 
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


    if args.seed is not None:
        set_random_seed(args.seed)

    args.cam = "excluded"
    
    

    args.test_on_val = False

    return args

def main(args):
    lecun_fix()
    if args is None:
        args = parse_args()    
    
    # Add uuid, timestamp and hostname for logging
    args.conf_jobnum = str(uuid.uuid4())
    args.conf_timestamp = str(datetime.datetime.now())
    args.conf_host = socket.gethostname()
    args.loadonmemory = int(not args.debug_mode)
    dataset = get_dataset(args)
    if args.n_epochs is None and isinstance(dataset, ContinualDataset):
        args.n_epochs = dataset.get_epochs()
    if args.batch_size is None:
        args.batch_size = dataset.get_batch_size()
    if hasattr(importlib.import_module('models.' + args.model), 'Buffer') and args.minibatch_size is None:
        args.minibatch_size = dataset.get_minibatch_size()

    backbone = dataset.get_backbone()
    loss = dataset.get_loss()
    model = get_model(args, backbone, loss, dataset.get_transform())
    dataset.load()
    
    # set job name
    # setproctitle.setproctitle('{}_{}_{}'.format(args.model, args.buffer_size if 'buffer_size' in args else 0, args.dataset))     
    setproctitle.setproctitle(f'{args.exp_desc}')
    
    args.wandb_tag=args.model
    mode = 'disabled' if args.debug_mode else 'online'
    wandb.init(project='miccai_coomil', entity='miccai_coomil', config=vars(args),tags=[args.wandb_tag],
                   name=str(args.model), mode=mode)
    args.wandb_url = wandb.run.get_url()

    if isinstance(dataset, ContinualDataset):
        train(model, dataset, args)
    else:
        assert not hasattr(model, 'end_task') or model.NAME == 'joint_gcl'
        ctrain(args)


if __name__ == '__main__':
    args = parse_args()
    args.logfolder="/work/H2020DeciderFicarra/fmiccolis/miccai_2025_workshop/outputs"
    args.debug_mode= 0
    
    experiments = []
    experiments += get_experiments(args)
    executor = submitit.AutoExecutor(folder=args.logfolder,slurm_max_num_timeout=30)
    executor.update_parameters(mem_gb=128, slurm_gpus_per_task=1, tasks_per_node=1, cpus_per_task=1, nodes=1,
                               slurm_additional_parameters={"cpus-per-task": 1, "account": "h2020deciderficarra", "exclude": ""},
                               timeout_min=300,
                               slurm_partition="all_usr_prod", slurm_signal_delay_s=300, slurm_array_parallelism=7)
    if args.debug_mode:
        executor.update_parameters(name="debug")
        executor.update_parameters(timeout_min=30)
        main(experiments[0])
    else:
        executor.map_array(main, experiments)
    # for fold in range(5,10,1):
    #     main(fold=fold)
