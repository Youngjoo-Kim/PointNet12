# *_*coding:utf-8 *_*
import os
import json
import warnings
import numpy as np
from tqdm import tqdm
from torch.utils.data import Dataset
import pickle as pkl
warnings.filterwarnings('ignore')
import sys
sys.path.append('.')
from colors import *

def load_data(root):
    fn_cache = 'experiment/shapenetcore_partanno_segmentation_benchmark_v0_normal.pkl'
    if not os.path.exists(fn_cache):
        cache = {}
        category = {}
        with open(os.path.join(root, 'synsetoffset2category.txt'), 'r') as f:
            for line in f:
                line = line.strip().split()
                category[line[0]] = line[1]
        print_err(category)

        print_info('Building cache...')
        for item in category.keys():
            dir_point = os.path.join(root, category[item])
            fns = os.listdir(dir_point)
            print_kv('item', item)
            for fn in tqdm(fns):
                token = fn.split('.')[0]
                fn_full = os.path.join(dir_point, fn)
                cache[token] = np.loadtxt(fn_full).astype(np.float32).tolist()
        
        print_info('Saving cache...')
        pkl.dump(cache, open(fn_cache,'wb'))
    else:
        print_info('Loading from cahce...')
        cache = pkl.load(open(fn_cache,'rb'))
        for key in cache.keys():
            cache[key] = np.array(cache[key])


def pc_normalize(pc):
    centroid = np.mean(pc, axis=0)
    pc = pc - centroid
    m = np.max(np.sqrt(np.sum(pc ** 2, axis=1)))
    pc = pc / m
    return pc

def jitter_point_cloud(batch_data, sigma=0.01, clip=0.05):
    """ Randomly jitter points. jittering is per point.
        Input:
          BxNx3 array, original batch of point clouds
        Return:
          BxNx3 array, jittered batch of point clouds
    """
    N, C = batch_data.shape
    assert(clip > 0)
    jittered_data = np.clip(sigma * np.random.randn(N, C), -1*clip, clip)
    jittered_data += batch_data
    return jittered_data

class PartNormalDataset(Dataset):
    def __init__(self, root, npoints=2500, split='train', normalize=True, jitter=False):
        self.npoints = npoints
        self.root = root
        self.category = {}
        self.normalize = normalize
        self.jitter = jitter

        with open(os.path.join(self.root, 'synsetoffset2category.txt'), 'r') as f:
            for line in f:
                line = line.strip().split()
                self.category[line[0]] = line[1]

        fn_split = os.path.join(self.root, 'train_test_split')
        with open(os.path.join(fn_split,'shuffled_train_file_list.json'), 'r') as f:
            train_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(fn_split,'shuffled_val_file_list.json'), 'r') as f:
            val_ids = set([str(d.split('/')[2]) for d in json.load(f)])
        with open(os.path.join(fn_split,'shuffled_test_file_list.json'), 'r') as f:
            test_ids = set([str(d.split('/')[2]) for d in json.load(f)])
            
        self.meta = {}
        for item in self.category:
            self.meta[item] = []
            dir_point = os.path.join(self.root, self.category[item])
            fns = sorted(os.listdir(dir_point))

            if split == 'trainval':
                fns = [fn for fn in fns if ((fn[0:-4] in train_ids) or (fn[0:-4] in val_ids))]
            elif split == 'train':
                fns = [fn for fn in fns if fn[0:-4] in train_ids]
            elif split == 'val':
                fns = [fn for fn in fns if fn[0:-4] in val_ids]
            elif split == 'test':
                fns = [fn for fn in fns if fn[0:-4] in test_ids]
            else:
                raise ValueError('Unknown split: %s. Exiting..' % (split))

            for fn in fns:
                self.meta[item].append(os.path.join(dir_point, fn))

        self.datapath = []
        for item in self.category:
            for fn in self.meta[item]:
                self.datapath.append((item, fn))

        self.classes = dict(zip(self.category, range(len(self.category))))
        print_kv('classes',self.classes)

        self.seg_classes = {'Earphone': [16, 17, 18], 'Motorbike': [30, 31, 32, 33, 34, 35], 'Rocket': [41, 42, 43],
                            'Car': [8, 9, 10, 11], 'Laptop': [28, 29], 'Cap': [6, 7], 'Skateboard': [44, 45, 46],
                            'Mug': [36, 37], 'Guitar': [19, 20, 21], 'Bag': [4, 5], 'Lamp': [24, 25, 26, 27],
                            'Table': [47, 48, 49], 'Airplane': [0, 1, 2, 3], 'Pistol': [38, 39, 40],
                            'Chair': [12, 13, 14, 15], 'Knife': [22, 23]}
        self.cache = {}


    def __getitem__(self, index):
        print_err('cached',len(self.cache.keys()), index)
        if index in self.cache:
            point_set, normal, seg, classi = self.cache[index]
        else:
            fn = self.datapath[index]
            cat = self.datapath[index][0]
            classi = self.classes[cat]
            classi = np.array([classi]).astype(np.int32)
            data = np.loadtxt(fn[1]).astype(np.float32)
            point_set = data[:, 0:3]
            normal = data[:, 3:6]
            seg = data[:, -1].astype(np.int32)
            self.cache[index] = (point_set, normal, seg, classi)
        
        if self.normalize:
            point_set = pc_normalize(point_set)
            
        if self.jitter:
            jitter_point_cloud(point_set)
        
        choice = np.random.choice(len(seg), self.npoints, replace=True)

        # resample
        point_set = point_set[choice, :]
        seg = seg[choice]
        normal = normal[choice, :]
        return point_set,classi, seg, normal


    def __len__(self):
        return len(self.datapath)

# class PartNormalDataset(Dataset):
#     def __init__(self, root, npoints=2500, split='train', normalize=True, jitter=False):
#         self.npoints = npoints
#         self.root = root
#         self.category = {}
#         self.normalize = normalize
#         self.jitter = jitter

#         with open(os.path.join(self.root, 'synsetoffset2category.txt'), 'r') as f:
#             for line in f:
#                 line = line.strip().split()
#                 self.category[line[0]] = line[1]

#         fn_split = os.path.join(self.root, 'train_test_split')
#         with open(os.path.join(fn_split,'shuffled_train_file_list.json'), 'r') as f:
#             train_ids = set([str(d.split('/')[2]) for d in json.load(f)])
#         with open(os.path.join(fn_split,'shuffled_val_file_list.json'), 'r') as f:
#             val_ids = set([str(d.split('/')[2]) for d in json.load(f)])
#         with open(os.path.join(fn_split,'shuffled_test_file_list.json'), 'r') as f:
#             test_ids = set([str(d.split('/')[2]) for d in json.load(f)])
            
#         self.meta = {}
#         for item in self.category:
#             self.meta[item] = []
#             dir_point = os.path.join(self.root, self.category[item])
#             fns = sorted(os.listdir(dir_point))

#             if split == 'trainval':
#                 fns = [fn for fn in fns if ((fn[0:-4] in train_ids) or (fn[0:-4] in val_ids))]
#             elif split == 'train':
#                 fns = [fn for fn in fns if fn[0:-4] in train_ids]
#             elif split == 'val':
#                 fns = [fn for fn in fns if fn[0:-4] in val_ids]
#             elif split == 'test':
#                 fns = [fn for fn in fns if fn[0:-4] in test_ids]
#             else:
#                 raise ValueError('Unknown split: %s. Exiting..' % (split))

#             for fn in fns:
#                 self.meta[item].append(os.path.join(dir_point, fn))

#         self.datapath = []
#         for item in self.category:
#             for fn in self.meta[item]:
#                 self.datapath.append((item, fn))

#         self.classes = dict(zip(self.category, range(len(self.category))))
#         print_kv('classes',self.classes)

#         self.seg_classes = {'Earphone': [16, 17, 18], 'Motorbike': [30, 31, 32, 33, 34, 35], 'Rocket': [41, 42, 43],
#                             'Car': [8, 9, 10, 11], 'Laptop': [28, 29], 'Cap': [6, 7], 'Skateboard': [44, 45, 46],
#                             'Mug': [36, 37], 'Guitar': [19, 20, 21], 'Bag': [4, 5], 'Lamp': [24, 25, 26, 27],
#                             'Table': [47, 48, 49], 'Airplane': [0, 1, 2, 3], 'Pistol': [38, 39, 40],
#                             'Chair': [12, 13, 14, 15], 'Knife': [22, 23]}
#         self.cache = {}


#     def __getitem__(self, index):
#         print_err('cached',len(self.cache.keys()), index)
#         if index in self.cache:
#             point_set, normal, seg, classi = self.cache[index]
#         else:
#             fn = self.datapath[index]
#             cat = self.datapath[index][0]
#             classi = self.classes[cat]
#             classi = np.array([classi]).astype(np.int32)
#             data = np.loadtxt(fn[1]).astype(np.float32)
#             point_set = data[:, 0:3]
#             normal = data[:, 3:6]
#             seg = data[:, -1].astype(np.int32)
#             self.cache[index] = (point_set, normal, seg, classi)
        
#         if self.normalize:
#             point_set = pc_normalize(point_set)
            
#         if self.jitter:
#             jitter_point_cloud(point_set)
        
#         choice = np.random.choice(len(seg), self.npoints, replace=True)

#         # resample
#         point_set = point_set[choice, :]
#         seg = seg[choice]
#         normal = normal[choice, :]
#         return point_set,classi, seg, normal


#     def __len__(self):
#         return len(self.datapath)