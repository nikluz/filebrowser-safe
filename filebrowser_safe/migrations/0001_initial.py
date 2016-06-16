# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='FileBrowserItem',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('path', models.CharField(max_length=512)),
                ('path_relative_directory', models.CharField(max_length=512)),
                ('filename', models.CharField(max_length=512)),
                ('url', models.CharField(max_length=512, null=True, blank=True)),
                ('extension', models.CharField(max_length=64, null=True, blank=True)),
                ('filetype', models.CharField(blank=True, max_length=64, null=True, choices=[(b'code', b'Code'), (b'image', b'Image'), (b'audio', b'Audio'), (b'video', b'Video'), (b'folder', b'Folder'), (b'document', b'Document')])),
                ('filesize', models.PositiveIntegerField(null=True, blank=True)),
                ('datetime', models.DateTimeField(null=True, blank=True)),
                ('parent', models.ForeignKey(blank=True, to='filebrowser_safe.FileBrowserItem', null=True)),
            ],
        ),
    ]
