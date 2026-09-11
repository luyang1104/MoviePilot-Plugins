"""配置表单与详情页的字典构建（MoviePilot 声明式页面协议）。"""

from __future__ import annotations

from typing import Dict, List, Tuple


def build_form() -> Tuple[List[dict], Dict]:
    """拼装插件配置页面，返回（页面配置, 数据结构）。"""
    return [
        {
            'component': 'VForm',
            'content': [
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'enabled',
                                        'label': '启用插件',
                                    }
                                }
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'notify',
                                        'label': '发送通知',
                                    }
                                }
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'del_source',
                                        'label': '删除源文件',
                                    }
                                }
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 3
                            },
                            'content': [
                                {
                                    'component': 'VSwitch',
                                    'props': {
                                        'model': 'del_history',
                                        'label': '删除历史',
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 4
                            },
                            'content': [
                                {
                                    'component': 'VSelect',
                                    'props': {
                                        'model': 'sync_type',
                                        'label': '媒体库同步方式',
                                        'items': [
                                            {'title': 'Webhook', 'value': 'webhook'},
                                            {'title': 'Scripter X', 'value': 'plugin'}
                                        ]
                                    }
                                }
                            ]
                        },
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                                'md': 8
                            },
                            'content': [
                                {
                                    'component': 'VTextField',
                                    'props': {
                                        'model': 'exclude_path',
                                        'label': '排除路径'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VTextarea',
                                    'props': {
                                        'model': 'library_path',
                                        'rows': '2',
                                        'label': '媒体库路径映射',
                                        'placeholder': '媒体服务器路径:MoviePilot路径（一行一个）'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '媒体库同步方式分为Webhook、Scripter X：'
                                                '1、Webhook需要Emby4.8.0.45及以上开启媒体删除的Webhook。'
                                                '2、Scripter X方式需要emby安装并配置Scripter X插件，无需配置执行周期。'
                                                '3、启用该插件后，非媒体服务器触发的源文件删除，也会同步处理下载器中的下载任务。'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '关于路径映射（转移后文件路径）：'
                                                'emby:/data/A.mp4,'
                                                'moviepilot:/mnt/link/A.mp4。'
                                                '路径映射填/data:/mnt/link。'
                                                '不正确配置会导致查询不到转移记录！（路径一样可不填）'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '排除路径：命中排除路径后请求云盘删除插件删除云盘资源。'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': 'Scripter X配置文档：'
                                                'https://github.com/thsrite/'
                                                'MediaSyncDel/blob/main/MoviePilot/MoviePilot.md'
                                    }
                                }
                            ]
                        }
                    ]
                },
                {
                    'component': 'VRow',
                    'content': [
                        {
                            'component': 'VCol',
                            'props': {
                                'cols': 12,
                            },
                            'content': [
                                {
                                    'component': 'VAlert',
                                    'props': {
                                        'type': 'info',
                                        'variant': 'tonal',
                                        'text': '路径映射配置文档：'
                                                'https://github.com/thsrite/MediaSyncDel/blob/main/path.md'
                                    }
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ], {
        "enabled": False,
        "notify": True,
        "del_source": False,
        "del_history": False,
        "library_path": "",
        "sync_type": "webhook",
        "exclude_path": "",
    }


def build_page(historys: List[dict]) -> List[dict]:
    """拼装插件详情页面：同步历史按时间降序的卡片列表。"""
    if not historys:
        return [
            {
                'component': 'div',
                'text': '暂无数据',
                'props': {
                    'class': 'text-center',
                }
            }
        ]
    # 数据按时间降序排序（缺失 del_time 的历史记录按空串兜底，避免比较 None 报 TypeError）
    historys = sorted(historys, key=lambda x: x.get('del_time') or '', reverse=True)
    # 拼装页面
    contents = []
    for history in historys:
        htype = history.get("type")
        title = history.get("title")
        unique = history.get("unique")
        year = history.get("year")
        season = history.get("season")
        episode = history.get("episode")
        image = history.get("image")
        del_time = history.get("del_time")

        sub_contents = [
            {
                'component': 'VCardText',
                'props': {
                    'class': 'pa-0 px-2'
                },
                'text': f'类型：{htype}'
            },
            {
                'component': 'VCardText',
                'props': {
                    'class': 'pa-0 px-2'
                },
                'text': f'标题：{title}'
            },
            {
                'component': 'VCardText',
                'props': {
                    'class': 'pa-0 px-2'
                },
                'text': f'年份：{year}'
            },
        ]
        if season:
            sub_contents += [
                {
                    'component': 'VCardText',
                    'props': {
                        'class': 'pa-0 px-2'
                    },
                    'text': f'季：{season}'
                },
                {
                    'component': 'VCardText',
                    'props': {
                        'class': 'pa-0 px-2'
                    },
                    'text': f'集：{episode}'
                },
            ]
        sub_contents.append(
            {
                'component': 'VCardText',
                'props': {
                    'class': 'pa-0 px-2'
                },
                'text': f'时间：{del_time}'
            }
        )

        contents.append(
            {
                'component': 'VCard',
                'content': [
                    {
                        "component": "VDialogCloseBtn",
                        "props": {
                            'innerClass': 'absolute top-0 right-0',
                        },
                        'events': {
                            'click': {
                                'api': 'plugin/LinkedMediaDel/delete_history',
                                'method': 'get',
                                'params': {
                                    'key': unique
                                }
                            }
                        },
                    },
                    {
                        'component': 'div',
                        'props': {
                            'class': 'd-flex justify-space-start flex-nowrap flex-row',
                        },
                        'content': [
                            {
                                'component': 'div',
                                'content': [
                                    {
                                        'component': 'VImg',
                                        'props': {
                                            'src': image,
                                            'height': 120,
                                            'width': 80,
                                            'aspect-ratio': '2/3',
                                            'class': 'object-cover shadow ring-gray-500',
                                            'cover': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'div',
                                'content': sub_contents
                            }
                        ]
                    }
                ]
            }
        )

    return [
        {
            'component': 'div',
            'props': {
                'class': 'grid gap-3 grid-info-card',
            },
            'content': contents
        }
    ]
