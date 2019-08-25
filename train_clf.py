import argparse
import os
import time
import datetime
import numpy as np
import torch
import torch.nn.parallel
import torch.utils.data
from torch.utils.data import DataLoader
import torch.nn.functional as F
from data_utils.ModelNetDataLoader import ModelNetDataLoader, load_data, class_names
from pathlib import Path
from tqdm import tqdm
from utils import test, save_checkpoint, select_avaliable, mkdir
from colors import *
from model.pointnet2 import PointNet2ClsMsg
from model.pointnet import PointNetCls, feature_transform_reguliarzer

def parse_args():
    parser = argparse.ArgumentParser('PointNet')
    parser.add_argument('--model_name', default='pointnet2', help='pointnet or pointnet2')
    parser.add_argument('--mode', default='train', help='train or eval')
    parser.add_argument('--batch_size', type=int, default=24, help='batch size in training')
    parser.add_argument('--epoch',  default=100, type=int, help='number of epoch in training')
    parser.add_argument('--learning_rate', default=0.001, type=float, help='learning rate in training')
    parser.add_argument('--gpu', type=str, default='0', help='specify gpu device')
    parser.add_argument('--train_metric', type=str, default=False, help='whether evaluate on training dataset')
    parser.add_argument('--optimizer', type=str, default='Adam', help='optimizer for training')
    parser.add_argument('--pretrain', type=str, default=None, help='whether use pretrain model')
    parser.add_argument('--decay_rate', type=float, default=1e-4, help='decay rate of learning rate')
    parser.add_argument('--rotation',  default=None, help='range of training rotation')
    parser.add_argument('--feature_transform', default=False, help="use feature transform in pointnet")
    return parser.parse_args()

def train(args):
    dataset_root = select_avaliable([
        '/media/james/MyPassport/James/dataset/ShapeNet/modelnet40_ply_hdf5_2048/',
        '/home/james/dataset/ShapeNet/modelnet40_ply_hdf5_2048/'
    ])

    experiment_dir = mkdir('./experiment/')
    checkpoints_dir = mkdir('./experiment/clf/%s/'%(args.model_name))

    print_info('Loading dataset ...')
    train_data, train_label, test_data, test_label = load_data(dataset_root, classification=True)
    print_kv('train_data',train_data.shape,'train_label' ,train_label.shape)
    print_kv('test_data',test_data.shape,'test_label', test_label.shape)
    
    if args.rotation is not None:
        ROTATION = (int(args.rotation[0:2]),int(args.rotation[3:5]))
        print_kv('The range of training rotation is:',ROTATION)
    else:
        ROTATION = None

    trainDataset = ModelNetDataLoader(train_data, train_label, rotation=ROTATION)
    trainDataLoader = DataLoader(trainDataset, batch_size=args.batch_size, shuffle=True)

    testDataset = ModelNetDataLoader(test_data, test_label, rotation=ROTATION)
    testDataLoader = torch.utils.data.DataLoader(testDataset, batch_size=args.batch_size, shuffle=False)

    print_kv('Building Model',args.model_name)
    if args.model_name == 'pointnet':
        num_class = 40
        model = PointNetCls(num_class,args.feature_transform).cuda()  
    else:
        model = PointNet2ClsMsg().cuda()

    if args.pretrain is not None:
        print_info('Use pretrain model...')
        checkpoint = torch.load(args.pretrain)
        start_epoch = checkpoint['epoch']
        model.load_state_dict(checkpoint['model_state_dict'])
    else:
        print_info('No existing model, starting training from scratch...')
        start_epoch = 0

    if args.optimizer == 'SGD':
        optimizer = torch.optim.SGD(model.parameters(), lr=0.01, momentum=0.9)
    elif args.optimizer == 'Adam':
        optimizer = torch.optim.Adam(model.parameters(),lr=args.learning_rate,
                                    betas=(0.9, 0.999),eps=1e-08,weight_decay=args.decay_rate)

    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)
    LEARNING_RATE_CLIP = 1e-5

    device_ids = [int(x) for x in args.gpu.split(',')]
    if len(device_ids) >= 2:
        torch.backends.cudnn.benchmark = True
        model.cuda(device_ids[0])
        model = torch.nn.DataParallel(model, device_ids=device_ids)
        print_info('Using multi GPU:',device_ids)
    else:
        model.cuda()
        print_info('Using single GPU:',device_ids)

    global_epoch = 0
    global_step = 0
    best_tst_accuracy = 0.0

    print_info('Start training...')
    for epoch in range(start_epoch,args.epoch):
        scheduler.step()
        lr = max(optimizer.param_groups[0]['lr'],LEARNING_RATE_CLIP)

        print_info('clf -> ',end='')
        print_kv('model:', args.model_name,'gpu:',args.gpu,'epoch:', '%d/%s' % (epoch, args.epoch),'lr:', lr)

        for param_group in optimizer.param_groups:
            param_group['lr'] = lr

        for batch_id, data in tqdm(enumerate(trainDataLoader, 0), total=len(trainDataLoader), smoothing=0.9):
            points, target = data
            target = target[:, 0]
            points = points.transpose(2, 1)
            points, target = points.cuda(), target.cuda()
            optimizer.zero_grad()
            model = model.train()
            pred, trans_feat = model(points)
            loss = F.nll_loss(pred, target.long())
            if args.feature_transform and args.model_name == 'pointnet':
                loss += feature_transform_reguliarzer(trans_feat) * 0.001
            loss.backward()
            optimizer.step()
            global_step += 1
        
        print_debug('clear cuda cache')
        torch.cuda.empty_cache()

        if args.train_metric:
            train_acc = test(model.eval(), trainDataLoader)
            print_kv('Train Accuracy', train_acc)

        acc = test(model, testDataLoader)
        print_kv('loss', '%.5f' % (loss.data))
        print_kv('Test Accuracy', '%.5f' % acc)

        if acc >= best_tst_accuracy:
            best_tst_accuracy = acc
            fn_pth = 'clf-%s-%.5f-%04d.pth'%(args.model_name, acc, epoch)
            print_kv('Saving model....', fn_pth)
            torch.save(model.state_dict(), os.path.join(checkpoints_dir,fn_pth))
        global_epoch += 1

    print_kv('Best Accuracy', best_tst_accuracy)
    print_info('End of training...')

def evaluate(args):
    dataset_root = select_avaliable([
        '/media/james/Ubuntu_Data/dataset/ShapeNet/modelnet40_ply_hdf5_2048/',
        '/media/james/MyPassport/James/dataset/ShapeNet/modelnet40_ply_hdf5_2048/',
        '/home/james/dataset/ShapeNet/modelnet40_ply_hdf5_2048/'
    ])

    experiment_dir = mkdir('./experiment/')
    checkpoints_dir = mkdir('./experiment/clf/%s/'%(args.model_name))

    print_info('Loading dataset ...')
    _, _, test_data, test_label = load_data(dataset_root, classification=True, train_data = False)
    print_kv('test_data',test_data.shape,'test_label', test_label.shape)
    
    testDataset = ModelNetDataLoader(test_data, test_label, rotation=args.rotation)
    testDataLoader = torch.utils.data.DataLoader(testDataset, batch_size=args.batch_size, shuffle=False)

    print_kv('Building Model',args.model_name)
    if args.model_name == 'pointnet':
        num_class = 40
        model = PointNetCls(num_class,args.feature_transform).cuda()  
    else:
        model = PointNet2ClsMsg().cuda()

    if args.pretrain is None:
        print_err('No pretrain model')
        return

    print_info('Loading pretrain model...')
    checkpoint = torch.load(args.pretrain)
    model.load_state_dict(checkpoint)
    model.eval()

    mean_correct = []
    for j, data in tqdm(enumerate(testDataLoader, 0)):
        points, target = data
        target = target[:, 0]
        points = points.transpose(2, 1)
        points, target = points.cuda(), target.cuda()
        pred, _ = model(points)
        pred_choice = pred.data.max(1)[1]
        correct = pred_choice.eq(target.long().data).cpu().sum()
        mean_correct.append(correct.item()/float(points.size()[0]))

        # print_kv('pred',pred.shape,'pred_choice',pred_choice.shape)
        # print_kv('points',points.shape,'target',target.shape, 'correct',correct.numpy())
        # print_kv('>',j,'Test Accuracy','%.5f' % (np.mean(mean_correct)))
        # gt = target.long().cpu().numpy()
        # prediction = pred_choice.cpu().numpy()

    print_kv('Test Accuracy','%.5f' % (np.mean(mean_correct)))

if __name__ == '__main__':
    args = parse_args()
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpu
    if args.mode == "train":
        train(args)
    else:
        evaluate(args)
